from gi.repository import GObject

from terminatorlib.util import dbg
from terminatorlib.tmux import layout

import string
ATTACH_ERROR_STRINGS = [b"can't find session terminator", b"no current session", b"no sessions"]
ALTERNATE_SCREEN_ENTER_CODES = [ b"\\033[?1049h" ]
ALTERNATE_SCREEN_EXIT_CODES  = [ b"\\033[?1049l" ]

notifications_mappings = {}


def notification(cls):
    notifications_mappings[cls.marker] = cls
    return cls


class Notification(object):

    marker = 'undefined'
    attributes = []

    def consume(self, line, out):
        pass

    def __str__(self):
        attributes = ['{}="{}"'.format(attribute, getattr(self, attribute, ''))
                      for attribute in self.attributes]
        return '{}[{}]'.format(self.marker, ', '.join(attributes))


@notification
class Result(Notification):

    marker = 'begin'
    attributes = ['begin_timestamp', 'code', 'result', 'end_timestamp',
                  'error']

    def consume(self, line, out):
        timestamp, code, _ = line.split(b' ')
        self.begin_timestamp = timestamp
        self.code = code
        result = []
        line = out.readline()[:-1]
        while not (line.startswith(b'%end') or line.startswith(b'%error')):
            result.append(line)
            line = out.readline()[:-1]
        self.result = result
        end, timestamp, code, _ = line.split(b' ')
        self.end_timestamp = timestamp
        self.error = end == b'%error'


@notification
class Exit(Notification):

    marker = 'exit'
    attributes = ['reason']

    def consume(self, line, *args):
        self.reason = line[0] if line else None


@notification
class LayoutChange(Notification):

    marker = 'layout-change'
    attributes = ['window_id', 'window_layout', 'window_visible_layout',
                  'window_flags']

    def consume(self, line, *args):
        # attributes not present default to None
        line_items = line.split(b' ')
        window_id, window_layout, window_visible_layout, window_flags = line_items + [None] * (len(self.attributes) - len(line_items))
        self.window_id = window_id
        self.window_layout = window_layout
        self.window_visible_layout = window_visible_layout
        self.window_flags = window_flags

@notification
class Output(Notification):

    marker = 'output'
    attributes = ['pane_id', 'output']

    def consume(self, line, *args):
        # pane_id = line[0]
        # output = ' '.join(line[1:])
        pane_id, output = line.split(b' ', 1)
        self.pane_id = pane_id
        self.output = output

@notification
class SessionChanged(Notification):

    marker = 'session-changed'
    attributes = ['session_id', 'session_name']

    def consume(self, line, *args):
        session_id, session_name = line.split(b' ')
        self.session_id = session_id
        self.session_name = session_name


@notification
class SessionRenamed(Notification):

    marker = 'session-renamed'
    attributes = ['session_id', 'session_name']

    def consume(self, line, *args):
        session_id, session_name = line.split(b' ')
        self.session_id = session_id
        self.session_name = session_name


@notification
class SessionsChanged(Notification):

    marker = 'sessions-changed'
    attributes = []


@notification
class UnlinkedWindowAdd(Notification):

    marker = 'unlinked-window-add'
    attributes = ['window_id']

    def consume(self, line, *args):
        window_id, = line.split(b' ')
        self.window_id = window_id


@notification
class WindowAdd(Notification):

    marker = 'window-add'
    attributes = ['window_id']

    def consume(self, line, *args):
        window_id, = line.split(b' ')
        self.window_id = window_id


@notification
class UnlinkedWindowClose(Notification):

    marker = 'unlinked-window-close'
    attributes = ['window_id']

    def consume(self, line, *args):
        window_id, = line.split(b' ')
        self.window_id = window_id


@notification
class WindowClose(Notification):

    marker = 'window-close'
    attributes = ['window_id']

    def consume(self, line, *args):
        window_id, = line.split(b' ')
        self.window_id = window_id


@notification
class UnlinkedWindowRenamed(Notification):

    marker = 'unlinked-window-renamed'
    attributes = ['window_id', 'window_name']

    def consume(self, line, *args):
        window_id, window_name = line.split(b' ')
        self.window_id = window_id
        self.window_name = window_name


@notification
class WindowRenamed(Notification):

    marker = 'window-renamed'
    attributes = ['window_id', 'window_name']

    def consume(self, line, *args):
        window_id, window_name = line.split(b' ')
        self.window_id = window_id
        self.window_name = window_name


class NotificationsHandler(object):

    def __init__(self, terminator):
        self.terminator = terminator
        self.layout_parser = layout.LayoutParser()

    def handle(self, notification):
        try:
            dbg('looking for method for {}'.format(notification.marker))  # JACK_TEST
            handler_method = getattr(self, 'handle_{}'.format(
                    notification.marker.replace('-', '_')))
            handler_method(notification)
        except AttributeError as e:  # JACK_TEST
            dbg('------- method for {} NOT FOUND: {}'.format(notification.marker, e))  # JACK_TEST
            pass
        except Exception as e:  # JACK_TEST
            dbg('something went wrong while handling {}: {}'.format(notification.marker, e))  # JACK_TEST

    def handle_begin(self, notification):
        dbg('### {}'.format(notification))
        assert isinstance(notification, Result)
        dbg('######## getting callback')  # JACK_TEST
        callback = self.terminator.tmux_control.requests.get()
        dbg(callback)  # JACK_TEST
        if notification.error:
            dbg('Request error: {}'.format(notification))
            if notification.result[0] in ATTACH_ERROR_STRINGS:
                # if we got here it means that attaching to an existing session
                # failed, invalidate the layout so the Terminator initialization
                # can pick up from where we left off
                self.terminator.initial_layout = {}
                self.terminator.tmux_control.reset()
            return
        if isinstance(callback, tuple):
            if len(callback) > 1:
                self.__getattribute__(callback[0])(notification.result, *callback[1:])
            else:
                self.__getattribute__(callback[0])(notification.result)
        elif callable(callback):
            callback(notification.result)

    def handle_output(self, notification):
        assert isinstance(notification, Output)
        pane_id = notification.pane_id
        output = notification.output
        dbg(pane_id)
        dbg(self.terminator.pane_id_to_terminal)
        terminal = self.terminator.pane_id_to_terminal.get(pane_id.decode())
        if not terminal:
            return
        for code in ALTERNATE_SCREEN_ENTER_CODES:
            if code in output:
                self.terminator.tmux_control.alternate_on = True
        for code in ALTERNATE_SCREEN_EXIT_CODES:
            if code in output:
                self.terminator.tmux_control.alternate_on = False
        # NOTE: using neovim, enabling visual-bell and setting t_vb empty results in incorrect
        # escape sequences (C-g) being printed in the neovim window; remove them until we can
        # figure out the root cause
        # terminal.vte.feed(output.replace("\033g", "").encode('utf-8'))
        dbg(output)
        terminal.vte.feed(output.decode('unicode-escape').encode('latin-1'))

    def handle_layout_change(self, notification):
        assert isinstance(notification, LayoutChange)
        GObject.idle_add(self.terminator.tmux_control.garbage_collect_panes)

    def handle_window_close(self, notification):
        assert isinstance(notification, WindowClose)
        GObject.idle_add(self.terminator.tmux_control.garbage_collect_panes)

    def pane_id_result(self, result):
        pane_id, marker = result[0].split(' ')
        terminal = self.terminator.find_terminal_by_pane_id(marker)
        terminal.pane_id = pane_id
        self.terminator.pane_id_to_terminal[pane_id] = terminal

    # NOTE: UNUSED; if we ever end up needing this, create the tty property in
    # the Terminal class first
    def pane_tty_result(self, result):
        dbg(result)
        pane_id, pane_tty = result[0].split(' ')
        # self.terminator.pane_id_to_terminal[pane_id].tty = pane_tty

    def garbage_collect_panes_result(self, result):
        pane_id_to_terminal = self.terminator.pane_id_to_terminal
        removed_pane_ids = pane_id_to_terminal.keys()

        for line in result:
            pane_id, pane_pid = line.split(b' ')
            try:
                removed_pane_ids.remove(pane_id)
                pane_id_to_terminal[pane_id].pid = pane_pid
            except ValueError:
                dbg("Pane already reaped, keep going.")
                continue

        if removed_pane_ids:
            def callback():
                for pane_id in removed_pane_ids:
                    terminal = pane_id_to_terminal.pop(pane_id, None)
                    if terminal:
                        terminal.close()
                return False
            GObject.idle_add(callback)

    def initial_layout_result(self, result):
        dbg('checking window layout')  # JACK_TEST
        window_layouts = []
        for line in result:
            window_layout = line.strip()
            dbg(window_layout)
            try:
                parsed_layout = self.layout_parser.parse(window_layout.decode())
            except Exception as e:
                dbg(e)
                exit(1)
            dbg(parsed_layout)
            window_layouts.extend(layout.parse_layout(parsed_layout[0]))
            # window_layouts.append(layout.parse_layout(window_layout))
        dbg('window layouts: {}'.format(window_layouts))  # JACK_TEST
        terminator_layout = layout.convert_to_terminator_layout(
                window_layouts)
        import pprint
        dbg(pprint.pformat(terminator_layout))
        self.terminator.initial_layout = terminator_layout

    def result_callback(self, result, pane_id):
        terminal = self.terminator.pane_id_to_terminal.get(pane_id)
        if not terminal:
            return
        output = b'\r\n'.join(l for l in result if l)
        dbg(output)
        terminal.vte.feed(output.decode('unicode-escape').encode('latin-1'))

    def initial_output_result_callback(self, pane_id):
        def result_callback(result):
            terminal = self.terminator.pane_id_to_terminal.get(pane_id)
            if not terminal:
                return
            output = '\r\n'.join(l for l in result if l)
            terminal.vte.feed(output.decode('string_escape'))
        return result_callback

    def terminate(self):
        def callback():
            for window in self.terminator.windows:
                window.emit('destroy')
        GObject.idle_add(callback)


def noop(*args):
    dbg('passed on notification: {}'.format(args))