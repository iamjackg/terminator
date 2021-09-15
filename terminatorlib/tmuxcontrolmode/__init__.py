import queue
import signal
import threading
import subprocess
import traceback
from collections import defaultdict

from . import notifications

from enum import Enum

import abc

ESCAPE_CODE = "\033"


def escape_sequence(seq):
    return "{}{}".format(ESCAPE_CODE, seq)


class Keys(Enum):
    BACKSPACE = "\b"
    TAB = "\t"
    INSERT = escape_sequence("[2~")
    DELETE = escape_sequence("[3~")
    PAGE_UP = escape_sequence("[5~")
    PAGE_DOWN = escape_sequence("[6~")
    HOME = escape_sequence("[1~")
    END = escape_sequence("[4~")
    UP = escape_sequence("[A")
    DOWN = escape_sequence("[B")
    RIGHT = escape_sequence("[C")
    LEFT = escape_sequence("[D")


#
# ARROW_KEYS = {Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Left, Gdk.KEY_Right}
# MOUSE_WHEEL = {
#     # TODO: make it configurable, e.g. like better-mouse-mode plugin
#     Gdk.ScrollDirection.UP: "C-y C-y C-y",
#     Gdk.ScrollDirection.DOWN: "C-e C-e C-e",
# }


def dbg(message):
    print(message)


class Tmux(abc.ABC):
    @abc.abstractmethod
    def send_input(self, input_data):
        pass

    @abc.abstractmethod
    def __iter__(self):
        pass

    @abc.abstractmethod
    def __next__(self):
        pass


class SubprocessTmux(Tmux):
    TMUX_BINARY = "tmux"

    def __init__(self, arguments):
        self.tmux = subprocess.Popen(
            [SubprocessTmux.TMUX_BINARY] + arguments,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            bufsize=0,
        )

        self.line_queue = queue.Queue()
        self._pipe_thread = threading.Thread(
            target=self._pipe_content,
        )
        self._pipe_thread.start()

    def _pipe_content(self):
        for line in iter(self.tmux.stdout.readline, b""):
            self.line_queue.put(line)
        self.line_queue.put(None)

    def send_input(self, input_data):
        try:
            self.tmux.stdin.write("{}\n".format(input_data).encode())
        except IOError:
            return

    def kill(self):
        self.tmux.send_signal(signal.SIGKILL)

    def __iter__(self):
        return self

    def __next__(self):
        next_line = self.line_queue.get(block=True)

        if next_line is not None:
            return next_line
        else:
            raise StopIteration


class TmuxControl(abc.ABC):
    def __init__(self, tmux, session_name):
        self.tmux = tmux
        self.session_name = session_name
        self.notification_consumer = notifications.NotificationConsumer(tmux)
        self._process_thread = None
        self.handler_map = defaultdict(list)
        self._command_queue = queue.Queue()
        self._command_lock = threading.Lock()

    def exit(self):
        self.tmux.kill()

    def add_handler(self, notification_marker, handler_function):
        self.handler_map[notification_marker].append(handler_function)

    def send_command(self, command, callback=None):
        with self._command_lock:
            self._command_queue.put(callback)
            self.tmux.send_input(command)

    def wait(self):
        if self._process_thread is not None:
            return self._process_thread.join()
        else:
            return

    def start(self):
        if self._process_thread is not None:
            return

        # Whenever we connect, we always get an initial Result. We don't want to process this one.
        self._command_queue.put(None)
        self._process_thread = threading.Thread(
            target=self.process_notifications,
        )
        self._process_thread.start()

    def send_content(self, content, pane_id):
        key_name_lookup = "-l" if ESCAPE_CODE in content else ""
        quote = "'" if "'" not in content else '"'
        self.send_command(
            "send-keys -t {} {} -- {}{}{}".format(
                pane_id, key_name_lookup, quote, content, quote
            )
        )

    def send_quoted_content(self, content, pane_id):
        key_name_lookup = "-l" if ESCAPE_CODE in content else ""
        self.send_command(
            "send-keys -t {} {} -- {}".format(pane_id, key_name_lookup, content)
        )

    def list_session_windows(self, session, callback=None):
        self.send_command(
            'list-windows -t {} -F "#{{window_id}} #{{window_layout}}"'.format(session),
            callback=callback,
        )

    def split_pane(
        self, cwd, horizontal, pane_id, command=None, marker="", callback=None
    ):
        orientation = "-h" if horizontal is True else "-v"
        tmux_command = 'split-window {} -t {} -P -F "#D {}"'.format(
            orientation, pane_id, marker
        )
        if cwd:
            tmux_command += ' -c "{}"'.format(cwd)
        if command:
            tmux_command += ' "{}"'.format(command)

        self.send_command(tmux_command, callback=callback)

    def new_window(self, cwd=None, command=None, marker="", callback=None):
        tmux_command = 'new-window -P -F "#D {}"'.format(marker)
        if cwd:
            tmux_command += ' -c "{}"'.format(cwd)
        if command:
            tmux_command += ' "{}"'.format(command)

        self.send_command(tmux_command, callback=callback)

    def capture_pane(self, pane, callback=None):
        self.send_command(
            "capture-pane -J -p -t {} -eC -S - -E -".format(pane),
            callback=callback,
        )

    def refresh_client(self, columns, rows):
        self.send_command("refresh-client -C {},{}".format(columns, rows))

    def resize_pane(self, pane_id, rows, cols):
        self.send_command('resize-pane -t "{}" -x {} -y {}'.format(pane_id, cols, rows))

    def process_notifications(self):
        for notification in self.notification_consumer:
            if type(notification) == str:
                break

            if isinstance(notification, notifications.Result):
                print("processing Result")
                try:
                    callback = self._command_queue.get(block=False)
                except queue.Empty:
                    pass
                else:
                    if callback is not None:
                        try:
                            callback(notification)
                        except Exception as e:
                            print(
                                "something went wrong while processing a command result {}: {}".format(
                                    notification.marker, e
                                )
                            )
            else:
                handlers_to_call = list()
                try:
                    handlers_to_call.append(
                        getattr(
                            self, "on_{}".format(notification.marker.replace("-", "_"))
                        )
                    )
                except AttributeError as e:
                    pass
                handlers_to_call += self.handler_map[notification.marker]

                for handler_method in handlers_to_call:
                    try:
                        handler_method(notification)
                    except Exception as e:
                        print(
                            "something went wrong while handling {}: {}".format(
                                notification.marker, e
                            )
                        )
                        traceback.print_exc()
