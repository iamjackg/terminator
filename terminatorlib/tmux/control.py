import threading
import subprocess

from multiprocessing import Queue

from pipes import quote
from gi.repository import Gtk, Gdk

from terminatorlib.tmux import notifications
from terminatorlib.util import dbg

from terminatorlib.tmuxcontrolmode import TmuxControl

ESCAPE_CODE = "\033"
TMUX_BINARY = "tmux"


def esc(seq):
    return "{}{}".format(ESCAPE_CODE, seq)


KEY_MAPPINGS = {
    Gdk.KEY_BackSpace: "\b",
    Gdk.KEY_Tab: "\t",
    Gdk.KEY_Insert: esc("[2~"),
    Gdk.KEY_Delete: esc("[3~"),
    Gdk.KEY_Page_Up: esc("[5~"),
    Gdk.KEY_Page_Down: esc("[6~"),
    Gdk.KEY_Home: esc("[1~"),
    Gdk.KEY_End: esc("[4~"),
    Gdk.KEY_Up: esc("[A"),
    Gdk.KEY_Down: esc("[B"),
    Gdk.KEY_Right: esc("[C"),
    Gdk.KEY_Left: esc("[D"),
}
ARROW_KEYS = {Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Left, Gdk.KEY_Right}
MOUSE_WHEEL = {
    # TODO: make it configurable, e.g. like better-mouse-mode plugin
    Gdk.ScrollDirection.UP: "C-y C-y C-y",
    Gdk.ScrollDirection.DOWN: "C-e C-e C-e",
}


class TerminatorTmuxControl(TmuxControl):
    def __init__(self, tmux, session_name):
        super().__init__(tmux, session_name)
        self.width = None
        self.height = None
        self.alternate_on = False
        self.is_zoomed = False

        self.pane_id_to_terminal = {}
        self.pane_alternate = {}

    def add_terminal(self, pane_id, terminal):
        self.pane_id_to_terminal[pane_id] = terminal

    def remove_terminal(self, pane_id):
        try:
            del(self.pane_id_to_terminal[pane_id])
        except KeyError:
            pass

        try:
            del(self.pane_alternate[pane_id])
        except KeyError:
            pass

    # def reset(self):
    #     self.tmux = self.input = self.output = self.width = self.height = None
    #
    # def spawn_tmux_child(
    #     self, command, marker, cwd=None, orientation=None, pane_id=None
    # ):
    #     if self.input:
    #         if orientation:
    #             self.split_window(
    #                 cwd=cwd,
    #                 orientation=orientation,
    #                 pane_id=pane_id,
    #                 command=command,
    #                 marker=marker,
    #             )
    #         else:
    #             self.new_window(cwd=cwd, command=command, marker=marker)
    #     else:
    #         self.new_session(cwd=cwd, command=command, marker=marker)
    #
    # def split_window(self, cwd, orientation, pane_id, command=None, marker=""):
    #     orientation = "-h" if orientation == "horizontal" else "-v"
    #     tmux_command = 'split-window {} -t {} -P -F "#D {}"'.format(
    #         orientation, pane_id, marker
    #     )
    #     if cwd:
    #         tmux_command += ' -c "{}"'.format(cwd)
    #     if command:
    #         tmux_command += ' "{}"'.format(command)
    #
    #     self._run_command(tmux_command, callback=("pane_id_result",))
    #
    # def new_window(self, cwd=None, command=None, marker=""):
    #     tmux_command = 'new-window -P -F "#D {}"'.format(marker)
    #     if cwd:
    #         tmux_command += ' -c "{}"'.format(cwd)
    #     if command:
    #         tmux_command += ' "{}"'.format(command)
    #
    #     self._run_command(tmux_command, callback=("pane_id_result",))
    #
    # def refresh_client(self, width, height):
    #     dbg("{}::{}: {}x{}".format("TmuxControl", "refresh_client", width, height))
    #     self.width = width
    #     self.height = height
    #     self._run_command("refresh-client -C {},{}".format(width, height))
    #
    # def garbage_collect_panes(self):
    #     self._run_command(
    #         'list-panes -s -t {} -F "#D {}"'.format(self.session_name, "#{pane_pid}"),
    #         callback=("garbage_collect_panes_result",),
    #     )
    #
    # def initial_layout(self):
    #     self._run_command(
    #         'list-windows -t {} -F "#{{window_layout}}"'.format(self.session_name),
    #         callback=("initial_layout_result",),
    #     )
    #
    # def initial_output(self, pane_id):
    #     self._run_command(
    #         "capture-pane -J -p -t {} -eC -S - -E -".format(pane_id),
    #         callback=("result_callback", pane_id),
    #     )
    #
    # def toggle_zoom(self, pane_id, zoom=False):
    #     self.is_zoomed = not self.is_zoomed
    #     if not zoom:
    #         self._run_command(
    #             "resize-pane -Z -x {} -y {} -t {}".format(
    #                 self.width, self.height, pane_id
    #             )
    #         )

    def send_keypress(self, event, pane_id):
        keyval = event.keyval
        state = event.state
        # dbg("KEY PRESSED")
        # dbg(keyval)
        # dbg(state)
        if keyval in KEY_MAPPINGS:
            key = KEY_MAPPINGS[keyval]
            if keyval in ARROW_KEYS and state & Gdk.ModifierType.CONTROL_MASK:
                key = "{}1;5{}".format(key[:2], key[2:])
        else:
            key = event.string

        if state & Gdk.ModifierType.MOD1_MASK:
            # Hack to have CTRL+SHIFT+Alt PageUp/PageDown/Home/End
            # work without these silly [... escaped characters
            if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK):
                return
            else:
                key = esc(key)

        if key == ";":
            key = "\\;"

        self.send_content(key, pane_id)

    # Handle mouse scrolling events if the alternate_screen is visible
    # otherwise let Terminator handle all the mouse behavior
    def send_mousewheel(self, event, pane_id):
        smooth_scroll_up = (
            event.direction == Gdk.ScrollDirection.SMOOTH and event.delta_y <= 0.0
        )
        smooth_scroll_down = (
            event.direction == Gdk.ScrollDirection.SMOOTH and event.delta_y > 0.0
        )
        if smooth_scroll_up:
            wheel = MOUSE_WHEEL[Gdk.ScrollDirection.UP]
        elif smooth_scroll_down:
            wheel = MOUSE_WHEEL[Gdk.ScrollDirection.DOWN]
        else:
            wheel = MOUSE_WHEEL[event.direction]

        if self.pane_alternate.get(pane_id):
            self.send_command("send-keys -t {} {}".format(pane_id, wheel))
            return True

        return False
    #
    # def display_pane_tty(self, pane_id):
    #     tmux_command = 'display -pt "{}" "#D {}"'.format(pane_id, "#{pane_tty}")
    #
    #     self._run_command(tmux_command, callback=("pane_tty_result",))
    #
    # def resize_pane(self, pane_id, rows, cols):
    #     if self.is_zoomed:
    #         # if the pane is zoomed, there is no need for tmux to
    #         # change the current layout
    #         return
    #     tmux_command = 'resize-pane -t "{}" -x {} -y {}'.format(pane_id, cols, rows)
    #
    #     self._run_command(tmux_command)
