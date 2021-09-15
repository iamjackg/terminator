import queue
import sys
import threading

notifications_mappings = {}


def notification(notification_class):
    notifications_mappings[notification_class.marker] = notification_class
    return notification_class


class Notification(object):
    marker = "undefined"
    attributes = []

    def __str__(self):
        attributes = [
            "{}={}".format(attribute, getattr(self, attribute, ""))
            for attribute in self.attributes
        ]
        return "{}[{}]".format(self.marker, ", ".join(attributes))


@notification
class Result(Notification):
    marker = "begin"
    attributes = ["begin_timestamp", "code", "result", "end_timestamp", "error"]

    def __init__(self, first_line, result, final_line):
        timestamp, code, _ = first_line.split(b" ")
        self.begin_timestamp = timestamp
        self.code = code
        self.result = result
        end, timestamp, code, _ = final_line.split(b" ")
        self.end_timestamp = timestamp
        self.error = end == b"%error"


@notification
class Exit(Notification):
    marker = "exit"
    attributes = ["reason"]

    def __init__(self, line):
        self.reason = line[0] if line else None


@notification
class LayoutChange(Notification):
    marker = "layout-change"
    attributes = ["window_id", "window_layout", "window_visible_layout", "window_flags"]

    def __init__(self, line):
        # attributes not present default to None
        line_items = line.decode("unicode-escape").split(" ")
        window_id, window_layout, window_visible_layout, window_flags = line_items + [
            None
        ] * (len(self.attributes) - len(line_items))
        self.window_id = window_id
        self.window_layout = window_layout
        self.window_visible_layout = window_visible_layout
        self.window_flags = window_flags


@notification
class Output(Notification):
    marker = "output"
    attributes = ["pane_id", "output"]

    def __init__(self, line):
        pane_id, output = line.split(b" ", 1)
        self.pane_id = pane_id.decode("latin-1")
        self.output = output


@notification
class SessionChanged(Notification):
    marker = "session-changed"
    attributes = ["session_id", "session_name"]

    def __init__(self, line):
        session_id, session_name = line.decode("unicode-escape").split(" ")
        self.session_id = session_id
        self.session_name = session_name


@notification
class SessionRenamed(Notification):
    marker = "session-renamed"
    attributes = ["session_id", "session_name"]

    def __init__(self, line):
        session_id, session_name = line.decode("unicode-escape").split(" ")
        self.session_id = session_id
        self.session_name = session_name


@notification
class SessionsChanged(Notification):
    marker = "sessions-changed"
    attributes = []

    def __init__(self, line):
        pass


@notification
class UnlinkedWindowAdd(Notification):
    marker = "unlinked-window-add"
    attributes = ["window_id"]

    def __init__(self, line):
        (window_id,) = line.decode("unicode-escape").split(" ")
        self.window_id = window_id


@notification
class WindowAdd(Notification):
    marker = "window-add"
    attributes = ["window_id"]

    def __init__(self, line):
        (window_id,) = line.decode("unicode-escape").split(" ")
        self.window_id = window_id


@notification
class UnlinkedWindowClose(Notification):
    marker = "unlinked-window-close"
    attributes = ["window_id"]

    def __init__(self, line):
        (window_id,) = line.decode("unicode-escape").split(" ")
        self.window_id = window_id


@notification
class WindowClose(Notification):
    marker = "window-close"
    attributes = ["window_id"]

    def __init__(self, line):
        (window_id,) = line.decode("unicode-escape").split(" ")
        self.window_id = window_id


@notification
class UnlinkedWindowRenamed(Notification):
    marker = "unlinked-window-renamed"
    attributes = ["window_id", "window_name"]

    def __init__(self, line):
        window_id, window_name = line.decode("unicode-escape").split(" ")
        self.window_id = window_id
        self.window_name = window_name


@notification
class WindowRenamed(Notification):
    marker = "window-renamed"
    attributes = ["window_id", "window_name"]

    def __init__(self, line):
        window_id, window_name = line.decode("unicode-escape").split(" ")
        self.window_id = window_id
        self.window_name = window_name


class NotificationConsumer(object):
    def __init__(self, tmux):
        self.tmux = tmux
        self.queue = queue.Queue()
        self._consumer_thread = threading.Thread(
            target=self.consume_loop,
        )
        self._consumer_thread.start()

    def __iter__(self):
        return self

    def __next__(self):
        return self.queue.get(block=True)

    def consume_loop(self):
        try:
            for line in self.tmux:
                line = line[:-1]
                # print("=>>>>> LINE RECEIVED: {}".format(line))
                line_fields = line[1:].split(b" ", 1)
                marker = line_fields[0].decode()

                # Special case for command output
                if marker == "begin":
                    final_line = None
                    output_lines = list()
                    for output_line in self.tmux:
                        # output_line = output_line.rstrip()
                        if not (
                            output_line.startswith(b"%end")
                            or output_line.startswith(b"%error")
                        ):
                            output_lines.append(output_line[:-1])
                        else:
                            final_line = output_line[:-1]
                            break
                    result_notification = Result(line_fields[1], output_lines, final_line)
                    print("Result:", result_notification)
                    self.queue.put(result_notification)
                else:
                    try:
                        data = line_fields[1]
                    except IndexError:
                        data = b""
                    # skip MOTD, anything that isn't coming from tmux control mode
                    try:
                        notification_instance = notifications_mappings[marker](data)
                        print("Notification: {}".format(notification_instance))  # JACK_TEST
                        self.queue.put(notification_instance)
                    except KeyError:
                        print("Unknown notification.")
                        continue
                    # print("consumed notification: {}".format(notification_instance))  # JACK_TEST
            print("Finished consumer loop")
        except Exception as e:
            sys.excepthook(*sys.exc_info())
        finally:
            print("notification consumer is quitting")
            self.queue.put("done")
