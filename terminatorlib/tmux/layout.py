import itertools
from itertools import zip_longest

import pyparsing as pp

# 13e1,124x26,0,0[124x6,0,0,1,124x6,0,7{62x6,0,7,5,61x6,63,7,6},124x12,0,14{62x12,0,14,3,61x12,63,14,4}]
class LayoutParser:
    """BNF representation for a Tmux Layout
    <layout>        :: <layout_name> <comma> <element>+ ;
    <element>       :: ( <container> | <pane> ) <comma>? ;
    <layout_name>   :: <hexadecimal>{4} ;
    <container>     :: <preamble> <start_token> <element>+ <end_token> ;
    <pane>          :: <preamble> <comma> <decimal> ;
    <preamble>      :: <size> <comma> <decimal> <comma> <decimal> ;
    <size>          :: <decimal> "x" <decimal> ;
    <start_token>   :: "{" | "[" ;
    <end_token>     :: "}" | "]" ;
    <decimal>       :: <decimal-digit>+ ;
    <hexadecimal>   :: <hex-digit>+ ;
    <decimal-digit> :: "0" | ... | "9" ;
    <hex-digit>     :: <decimal-digit> | "a" | ... | "f" ;
    <comma>         :: "," ;
    """

    layout_parser = None

    def __init__(self):
        decimal = pp.Word(pp.nums)

        comma = pp.Suppress(pp.Literal(","))
        start_token = pp.Literal("{") | pp.Literal("[")
        end_token = pp.Suppress(pp.Literal("}") | pp.Literal("]"))

        layout_name = pp.Suppress(pp.Word(pp.hexnums, min=4, max=4))
        size = decimal("width") + pp.Suppress(pp.Literal("x")) + decimal("height")

        preamble = size + comma + decimal("x") + comma + decimal("y")
        pane = pp.Group(preamble + comma + decimal("pane_id"))
        element = pp.Forward()  # will be defined later
        container = pp.Group(preamble + start_token + pp.OneOrMore(element) + end_token)

        element << (container | pane) + pp.Optional(comma)

        self.layout_parser = layout_name + comma + pp.OneOrMore(element)

    def parse(self, layout):
        parsed = self.layout_parser.parseString(layout)
        return parsed.asList()


def parse_layout(layout):
    """Apply our application logic to the parsed layout.

    Arguments:
    layout -- Layout parsed by LayoutParser.parse(),
              it is represented as a nested list; each nested
              list has the following format:
              [0]  : width,
              [1]  : height,
              [2]  : position on x axis,
              [3]  : position on y axis,
              [4]  : '{' if the current element is a horizontal splits container,
                     '[' if the current element is a vertical splits container,
                     '%[0-9]+' if the current element is a pane
              [5+] : if present, they are nested lists with the same structure

    """
    result = []

    children = []
    for item in layout[5:]:
        children.extend(parse_layout(item))

    if layout[4] == "{":
        result.append(Horizontal(layout[0], layout[1], layout[2], layout[3], children))

    elif layout[4] == "[":
        result.append(Vertical(layout[0], layout[1], layout[2], layout[3], children))
    else:
        result.append(
            Pane(layout[0], layout[1], layout[2], layout[3], "%{}".format(layout[4]))
        )

    return result


def convert_to_terminator_layout(window_layouts, total_columns=0, total_rows=0):
    assert len(window_layouts) > 0
    result = {}
    pane_index = 0
    window_name = "window0"
    parent_name = window_name
    result[window_name] = {"type": "Window", "parent": ""}
    if total_columns and total_rows:
        result[window_name]["tmux_size"] = [total_columns, total_rows]
    if len(window_layouts) > 1:
        notebook_name = "notebook0"
        result[notebook_name] = {"type": "Notebook", "parent": parent_name}
        parent_name = notebook_name
    order = 0
    for window_layout in window_layouts:
        converter = _get_converter(window_layout)
        pane_index, order = converter(
            result, parent_name, window_layout, pane_index, order
        )
    return result


class Container(object):
    def __init__(self, width, height, x, y):
        self.width = width
        self.height = height
        self.x = x
        self.y = y

    def __str__(self):
        return "{}[width={}, height={}, x={}, y={}, {}]".format(
            self.__class__.__name__,
            self.width,
            self.height,
            self.x,
            self.y,
            self._child_str(),
        )

    __repr__ = __str__

    def _child_str(self):
        raise NotImplementedError()


class Window(Container):
    def __init__(self, width, height, x, y):
        super(Pane, self).__init__(width, height, x, y)


class Pane(Container):
    def __init__(self, width, height, x, y, pane_id):
        super(Pane, self).__init__(width, height, x, y)
        self.pane_id = pane_id

    def _child_str(self):
        return "pane_id={}".format(self.pane_id)

    def __hash__(self):
        return hash(self.pane_id)

    def __eq__(self, other):
        if isinstance(other, Pane):
            return self.pane_id == other.pane_id
        else:
            return False


class Vertical(Container):
    def __init__(self, width, height, x, y, children):
        super(Vertical, self).__init__(width, height, x, y)
        self.children = children

    def _child_str(self):
        return "children={}".format(self.children)

    def __eq__(self, other):
        if isinstance(other, Vertical):
            return self.children == other.children
        else:
            return False


class Horizontal(Container):
    def __init__(self, width, height, x, y, children):
        super(Horizontal, self).__init__(width, height, x, y)
        self.children = children

    def _child_str(self):
        return "children={}".format(self.children)

    def __eq__(self, other):
        if isinstance(other, Horizontal):
            return self.children == other.children
        else:
            return False


def _covert_pane_to_terminal(result, parent_name, pane, pane_index, order):
    assert isinstance(pane, Pane)
    terminal = _convert(parent_name, "Terminal", pane, order)
    order += 1
    terminal["tmux"]["pane_id"] = pane.pane_id
    result["terminal{}".format(pane.pane_id[1:])] = terminal
    return pane_index, order


def _convert_vertical_to_vpane(
    result, parent_name, vertical_or_children, pane_index, order
):
    return _convert_container_to_terminator_pane(
        result, parent_name, vertical_or_children, pane_index, Vertical, order
    )


def _convert_horizontal_to_hpane(
    result, parent_name, horizontal_or_children, pane_index, order
):
    return _convert_container_to_terminator_pane(
        result, parent_name, horizontal_or_children, pane_index, Horizontal, order
    )


def _convert_container_to_terminator_pane(
    result, parent_name, container_or_children, pane_index, pane_type, order
):
    terminator_type = "VPaned" if issubclass(pane_type, Vertical) else "HPaned"
    if isinstance(container_or_children, pane_type):
        container = container_or_children
        pane = _convert(parent_name, terminator_type, container_or_children, order)
        order += 1
        children = container.children
    else:
        children = container_or_children
        if len(children) == 1:
            child = children[0]
            child_converter = _get_converter(child)
            return child_converter(result, parent_name, child, pane_index, order)
        pane = {"type": terminator_type, "parent": parent_name}
    pane_name = "pane{}".format(pane_index)
    result[pane_name] = pane
    parent_name = pane_name
    pane_index += 1
    child1 = children[0]
    child1_converter = _get_converter(child1)
    pane_index, order = child1_converter(result, parent_name, child1, pane_index, order)
    pane_index, order = _convert_container_to_terminator_pane(
        result, parent_name, children[1:], pane_index, pane_type, order
    )
    return pane_index, order


converters = {
    Pane: _covert_pane_to_terminal,
    Vertical: _convert_vertical_to_vpane,
    Horizontal: _convert_horizontal_to_hpane,
}


def _get_converter(container):
    try:
        return converters[type(container)]
    except KeyError:
        raise ValueError("Illegal window layout: {}".format(container))


def _convert(parent_name, type_name, container, order):
    assert isinstance(container, Container)
    return {
        "type": type_name,
        "parent": parent_name,
        "order": order,
        "tmux": {
            "width": container.width,
            "height": container.height,
            "x": container.x,
            "y": container.y,
        },
    }


def compare_layouts(old_layout, new_layout):
    if type(old_layout) != type(new_layout):
        print(type(old_layout), type(new_layout))
        return [old_layout, new_layout]
    else:
        if isinstance(old_layout, (Vertical, Horizontal)):
            for children in zip_longest(old_layout.children, new_layout.children, fillvalue=None):
                result = compare_layouts(*children)
                if result:
                    return result


def get_all_panes(layout):
    items_to_explore = [layout]
    panes = set()

    for item in items_to_explore:
        if isinstance(item, Pane):
            panes.add(item)
        else:
            items_to_explore.extend(item.children)

    return panes


def get_pane_parent(pane, layout):
    items_to_explore = [layout]

    for item in items_to_explore:
        if isinstance(item, (Vertical, Horizontal)):
            if pane in item.children:
                return item
            else:
                items_to_explore.extend(item.children)

    return None


def compare_terminator_layouts(old_layout, new_layout):
    added_stuff = {}
    changed_stuff = {}
    removed_stuff = {}
    for key in set(old_layout.keys()) | set(new_layout.keys()):
        if key not in old_layout:
            print("New: ", key, new_layout[key])
            added_stuff[key] = new_layout[key]
        elif key not in new_layout:
            print("Removed: ", key, old_layout[key])
            removed_stuff[key] = old_layout[key]
        elif new_layout[key] != old_layout[key]:
            print("Changed: \n\t", key, old_layout[key], "\n\t", key, new_layout[key])
            changed_stuff[key] = [old_layout[key], new_layout[key]]

    return added_stuff, changed_stuff, removed_stuff
