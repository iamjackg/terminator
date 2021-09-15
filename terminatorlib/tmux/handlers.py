from gi.repository import GObject

from collections import OrderedDict

import terminatorlib.tmux.control
from terminatorlib import factory
from terminatorlib.util import dbg
from terminatorlib.tmux import layout

ALTERNATE_SCREEN_ENTER_CODES = [b"\\033[?1049h"]
ALTERNATE_SCREEN_EXIT_CODES = [b"\\033[?1049l"]


class NotificationsHandler(object):
    def __init__(self, terminator, tmux_control):
        self.terminator = terminator
        self.tmux_control = tmux_control
        self.layout_parser = layout.LayoutParser()

        self.maker = factory.Factory()
        
        self.tmux_control.add_handler('output', self.handle_output)
        self.tmux_control.add_handler('layout-change', self.handle_layout_change)

        self.layouts = OrderedDict()
        self.terminator_layout = None

    def find_sibling(self, item_name, item_data, data_dict):
        for potential_sibling_name, potential_sibling_data in data_dict.items():
            if item_data['parent'] == potential_sibling_data['parent'] and item_name != potential_sibling_name:
                return potential_sibling_name, potential_sibling_data

    def find_children(self, item_name, data_dict):
        children = {}
        for potential_child_name, potential_child_data in data_dict.items():
            if potential_child_data['parent'] == item_name:
                children[potential_child_name] = potential_child_data

        return children

    def find_closest_terminal(self, item_name, data_dict):
        level = 0
        elements = []

    def handle_layout_change(self, result):
        new_parsed_layout = self.layout_parser.parse(result.window_layout)
        new_layout_struct = layout.parse_layout(new_parsed_layout[0])
        # print("Old layout:", self.layouts[result.window_id])
        # print("New layout:", new_layout_struct[0])
        # print(layout.compare_layouts(, new_layout_struct[0]))
        old_layout_panes = layout.get_all_panes(self.layouts[result.window_id])
        new_layout_panes = layout.get_all_panes(new_layout_struct[0])
        deleted_panes = old_layout_panes - new_layout_panes
        new_panes = new_layout_panes - old_layout_panes
        if deleted_panes:
            def callback():
                for pane in deleted_panes:
                    terminal = self.tmux_control.pane_id_to_terminal[pane.pane_id]
                    terminal.close()
                return False

            GObject.idle_add(callback)
        elif new_panes:
            new_pane = new_panes.pop()  # There should only ever be one
            parent = layout.get_pane_parent(new_pane, new_layout_struct[0])
            if parent is not None:
                previous_sibling = parent.children[parent.children.index(new_pane) - 1]
                print(previous_sibling)
                old_terminal = self.tmux_control.pane_id_to_terminal[previous_sibling.pane_id]
                old_terminal_parent = old_terminal.get_parent()

                new_terminal = self.maker.make('Terminal')
                new_terminal.set_cwd(old_terminal.cwd)
                new_terminal.create_layout({'tmux': {'pane_id': new_pane.pane_id, 'width': new_pane.width, 'height': new_pane.height}})
                new_terminal.titlebar.update()

                vertical = isinstance(parent, layout.Vertical)
                old_terminal_first = True
                old_terminal_parent.split_axis(old_terminal, vertical=vertical, sibling=new_terminal, widgetfirst=old_terminal_first)

        # temporary_new_layout = self.layouts.copy()
        # temporary_new_layout[result.window_id] = new_layout_struct[0]
        #
        # terminator_layout = layout.convert_to_terminator_layout(list(temporary_new_layout.values()))
        # # print("self.terminator_layout: ", self.terminator_layout)
        # # print("terminator_layout: ", terminator_layout)
        # added_stuff, changed_stuff, removed_stuff = layout.compare_terminator_layouts(self.terminator_layout, terminator_layout)
        #
        # # Removed stuff must be processed first, so we know if we can ignore certain parent changes in the changed items.
        # # When a terminal is closed, Terminator is smart enough to remove any Panes that are left with only one terminal.
        # removed_panes = set()
        # removed_terminals = set()
        # for removed_item_name, removed_item in removed_stuff.items():
        #     if removed_item['type'] == 'Terminal':
        #         removed_terminals.add(removed_item['tmux']['pane_id'])
        #     elif removed_item['type'] in ('HPaned', 'VPaned'):
        #         removed_panes.add(removed_item_name)
        #
        # # Closing a terminal causes Terminator to automagically re-establish the layout, so we don't really need to process the
        # # rest of the changes
        # if removed_terminals:
        #     def callback():
        #         for pane_id in removed_terminals:
        #             terminal = self.tmux_control.pane_id_to_terminal[pane_id]
        #             terminal.close()
        #         return False
        #
        #     GObject.idle_add(callback)
        # else:
        #     for new_item_name, new_item_data in added_stuff.items():
        #         if new_item_data['type'] == 'Terminal':
        #             parent_id = new_item_data['parent']
        #             new_container_pane = added_stuff.get(parent_id) or changed_stuff.get(parent_id)[1]
        #             sibling_name, sibling_data = self.find_sibling(new_item_name, new_item_data, terminator_layout)
        #
        #             # We found our sibling
        #             if sibling_data['type'] == 'Terminal':
        #                 old_terminal = self.tmux_control.pane_id_to_terminal[sibling_data['tmux']['pane_id']]
        #                 old_terminal_parent = old_terminal.get_parent()
        #
        #                 new_terminal = self.maker.make('Terminal')
        #                 new_terminal.set_cwd(old_terminal.cwd)
        #                 new_terminal.create_layout(new_item_data)
        #                 new_terminal.titlebar.update()
        #
        #                 vertical = new_container_pane['type'] == 'VPaned'
        #                 old_terminal_first = sibling_data['order'] < new_item_data['order']
        #                 old_terminal_parent.split_axis(old_terminal, vertical=vertical, sibling=new_terminal, widgetfirst=old_terminal_first)
        #             else:
        #                 print(sibling_name, sibling_data['type'])
        #     # # Alright, this stuff is pretty tough to understand. I'll try to leave some comments to explain what's going on.
        #     # # We start by looking at all the items that have changed, obviously.
        #     # for changed_item_name, (changed_item_old, changed_item_new) in changed_stuff.items():
        #     #     if changed_item_old['parent'] != changed_item_new['parent']:
        #     #         if changed_item_new['parent'].startswith('pane') and changed_item_old['parent'] not in removed_panes:  # TODO: check if I can remove the second clause
        #     #             # Before we do anything, let's check if there are any other items whose parent has changed to ours
        #     #             parent_just_changed_name = False
        #     #             for sibling_item_name, (sibling_old_item, sibling_new_item) in changed_stuff.items():
        #     #                 if sibling_item_name != changed_item_name and sibling_new_item['parent'] == changed_item_new['parent']:
        #     #                     parent_just_changed_name = True
        #     #                     print(changed_item_name, "changed parent to", changed_item_new['parent'], "but so did",
        #     #                           sibling_item_name)
        #     #                     break
        #     #             if parent_just_changed_name:
        #     #                 # We don't actually have to do anything here
        #     #                 continue
        #     #
        #     #     if changed_item_old['type'] == 'Terminal':
        #     #         # The thing that changed was a terminal -- now to determine _what_ changed
        #     #         if changed_item_old['parent'] != changed_item_new['parent']:
        #     #             # There are a few reasons the parent could be different:
        #     #             # - the terminal is not alone anymore and is now part of a split, so the parent changed from a notebook/window/split
        #     #             #   to an entirely new split (a "pane" in Terminator terms)
        #     #             # - nothing has actually changed, but a new pane was added somewhere _before_ this terminal appears, so the parent's
        #     #             #   name has changed (e.g. from pane2 to pane3). If we can find another terminal whose parent also changed from pane2
        #     #             #   to pane3, then we're sure that nothing actually needs to be done here.
        #     #             if changed_item_new['parent'].startswith('pane') and changed_item_old['parent'] not in removed_panes:  # TODO: check if I can remove the second clause
        #     #                 if changed_item_new['parent'] in added_stuff:
        #     #                     new_container_pane = added_stuff[changed_item_new['parent']]
        #     #
        #     #                     new_terminal_data = None
        #     #                     for added_item in added_stuff.values():
        #     #                         if added_item['type'] == 'Terminal' and added_item['parent'] == changed_item_new['parent']:
        #     #                             new_terminal_data = added_item
        #     #                             break
        #     #
        #     #                     if new_terminal_data is None:
        #     #                         # we searched for a new terminal that was added in the new split, but there wasn't one.
        #     #                         # this probably means that there isn't a new split here, and the terminal simply moved pane
        #     #                         # together with its sibling
        #     #                         continue
        #     #
        #     #                     old_terminal = self.tmux_control.pane_id_to_terminal[changed_item_new['tmux']['pane_id']]
        #     #                     old_terminal_parent = old_terminal.get_parent()
        #     #
        #     #                     new_terminal = self.maker.make('Terminal')
        #     #                     new_terminal.set_cwd(old_terminal.cwd)
        #     #                     new_terminal.create_layout(new_terminal_data)
        #     #                     new_terminal.titlebar.update()
        #     #
        #     #                     vertical = new_container_pane['type'] == 'VPaned'
        #     #                     old_terminal_first = changed_item_old['order'] < new_terminal_data['order']
        #     #                     old_terminal_parent.split_axis(old_terminal, vertical=vertical, sibling=new_terminal, widgetfirst=old_terminal_first)
        # self.terminator_layout = terminator_layout
        self.layouts[result.window_id] = new_layout_struct[0]

    def handle_output(self, result):
        pane_id = result.pane_id
        output = result.output
        terminal = self.tmux_control.pane_id_to_terminal.get(pane_id)
        if not terminal:
            return
        for code in ALTERNATE_SCREEN_ENTER_CODES:
            if code in output:
                self.tmux_control.pane_alternate[pane_id] = True
        for code in ALTERNATE_SCREEN_EXIT_CODES:
            if code in output:
                self.tmux_control.pane_alternate[pane_id] = False
        # NOTE: using neovim, enabling visual-bell and setting t_vb empty results in incorrect
        # escape sequences (C-g) being printed in the neovim window; remove them until we can
        # figure out the root cause
        # terminal.vte.feed(output.replace("\033g", "").encode('utf-8'))
        terminal.write_to_terminal(output)

    def set_initial_layout(self, result):
        self.terminator.initial_layout = self.list_windows_result_to_layout(result)
        self.terminator_layout = self.list_windows_result_to_layout(result)

    def list_windows_result_to_layout(self, result):
        import pprint

        window_layouts = []
        total_columns = 0
        total_rows = 0
        for line in result.result:
            window_layout = line.strip()
            window_layout = window_layout.decode()
            window_id, window_layout_string = window_layout.split(" ", 1)
            dbg(f"window_layout: {window_layout}")
            parsed_layouts = self.layout_parser.parse(window_layout_string)
            this_window_layout = parsed_layouts[0]
            total_columns, total_rows = map(int, this_window_layout[:2])
            this_window_parsed_layout = layout.parse_layout(this_window_layout)[0]
            dbg(f"parsed_layouts: {parsed_layouts}")
            window_layouts.append(this_window_parsed_layout)
            self.layouts[window_id] = this_window_parsed_layout
        dbg(f"window_layouts: {pprint.pformat(window_layouts)}")
        terminator_layout = layout.convert_to_terminator_layout(window_layouts, total_columns=total_columns, total_rows=total_rows)

        dbg('Final layout below:')
        dbg(pprint.pformat(terminator_layout))

        return terminator_layout
