import re
from typing import List, Dict
import uiautomator2
import xml.etree.ElementTree as ET
import rtree
from lxml import etree
class Uiautomator2_Helper:
    def __init__(self, device=None):
        if device is None:
            from droidbot.device import Device

            device = Device()
        self.device: Device = device

        self.u2: uiautomator2.Device = device.u2
        # self.u2 = uiautomator2.connect("emulator-5554")
        self.ignore_ad: bool = device.ignore_ad
        if self.ignore_ad:
            import re

            self.__first_cap_re = re.compile("(.)([A-Z][a-z]+)")
            self.__all_cap_re = re.compile("([a-z0-9])([A-Z])")

    def __id_convert(self, name):
        name = name.replace(".", "_").replace(":", "_").replace("/", "_")
        s1 = self.__first_cap_re.sub(r"\1_\2", name)
        return self.__all_cap_re.sub(r"\1_\2", s1).lower()

    def __view_tree_to_list(self, view_tree, view_list):
        tree_id = len(view_list)
        view_tree['temp_id'] = tree_id

        bounds = [[-1, -1], [-1, -1]]
        bounds[0][0] = view_tree['bounds'][0]
        bounds[0][1] = view_tree['bounds'][1]
        bounds[1][0] = view_tree['bounds'][2]
        bounds[1][1] = view_tree['bounds'][3]
        width = bounds[1][0] - bounds[0][0]
        height = bounds[1][1] - bounds[0][1]
        view_tree['size'] = "%d*%d" % (width, height)
        view_tree['bounds'] = bounds

        view_list.append(view_tree)
        children_ids = []
        for child_tree in view_tree['children']:
            if self.ignore_ad and child_tree['resource_id'] is not None:
                id_word_list = self.__id_convert(child_tree['resource_id']).split('_')
                if "ad" in id_word_list or "banner" in id_word_list:
                    continue
            child_tree['parent'] = tree_id
            self.__view_tree_to_list(child_tree, view_list)
            children_ids.append(child_tree['temp_id'])
        view_tree['children'] = children_ids

    def xml_to_dict(self, element) -> Dict:
        try:
            result = {}

            # Process attributes
            attributes = {
                "package": element.get("package"),
                "visible": element.get("visible-to-user") == "true",
                "checkable": element.get("checkable") == "true",
                "child_count": len(element),
                "editable": element.get("class") == "android.widget.EditText",
                "clickable": element.get("clickable") == "true",
                "is_password": element.get("password") == "true",
                "focusable": element.get("focusable") == "true",
                "enabled": element.get("enabled") == "true",
                "content_description": element.get("content-desc")
                if element.get("content-desc")
                else None,
                "covered": element.get("covered") == "true",
            }

            result = attributes

            # Recursively process children
            for child in element:
                child_data = self.xml_to_dict(child)
                if "children" in result:
                    result["children"].append(child_data)
                else:
                    result["children"] = [child_data]
            if len(element) == 0:
                result["children"] = []
            result["focused"] = element.get("focused") == "true"

            # Remove the square brackets and split the string by commas
            split_values = (
                element.get("bounds")
                .replace("][", ",")
                .replace("]", "")
                .replace("[", "")
                .split(",")
            )
            # Convert the substrings to integers and create a list
            integer_list = [int(value) for value in split_values]

            result["bounds"] = integer_list

            result["resource_id"] = (
                element.get("resource-id") if element.get("resource-id") else None
            )
            result["checked"] = element.get("checked") == "true"
            result["text"] = element.get("text") if element.get("text") else None
            result["class"] = element.get("class")
            result["scrollable"] = element.get("scrollable") == "true"
            result["selected"] = element.get("selected") == "true"
            result["long_clickable"] = element.get("long-clickable") == "true"

            return result
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.u2.press("home")
            return {}
    def add_enter_button_from_keyboard_into_view_list(self, view_list: List):
        """
        add the enter button from the keyboard into the view list
        :param view_list: the view list
        :return: None
        """
        enter_button = self.u2(resourceId="com.google.android.inputmethod.latin:id/key_pos_ime_action")
        if enter_button.exists:
            bounds = enter_button.info['bounds']
            view = {
                "package": "com.google.android.inputmethod.latin",
                "visible": True,
                "checkable": False,
                "child_count": 0,
                "editable": False,
                "clickable": True,
                "is_password": False,
                "focusable": True,
                "enabled": True,
                "content_description": "Search",
                "children": [],
                "focused": False,
                "bounds": [[bounds['left'], bounds['top']], [bounds['right'], bounds['bottom']]],
                "resource_id": "com.google.android.inputmethod.latin:id/key_pos_ime_action",
                "checked": False,
                "text": None,
                "class": "android.widget.Button",
                "scrollable": False,
                "selected": False,
                "long_clickable": False,
                "size": f"{bounds['right'] - bounds['left']}*{bounds['bottom'] - bounds['top']}",
                "parent": -1,
                "temp_id": len(view_list),
                }
            view_list.append(view)
        
    def select_target_root_node(self, xml):
        """
        select a target root node from the view tree
        :param xml: the xml
        :return: the selected root node
        """
        exclude_package = ["com.android.systemui","com.github.uiautomator","com.google.android.inputmethod.latin"]
        # iterate all the root nodes from the xml node, and select the one we want
        root = ET.fromstring(xml)
        child_list = []
        for child in root:
            if child.tag == "node" and child.get("package") in exclude_package:
                continue
            child_list.append(child)
        if len(child_list) == 1:
            return child_list[0]
        # if there are multiple root nodes, we select the one which has the largest number of child nodes
        max_child_num = 0
        target_child = None
        for child in child_list:
            child_num = len(child.findall(".//node"))
            if child_num > max_child_num:
                max_child_num = child_num
                target_child = child
        if max_child_num > 0:
            return target_child

        return None

    def dump_view(self) -> Dict:
        """
        dump the current view
        :return: the view tree
        """
        xml = self.u2.dump_hierarchy()

        root = etree.fromstring(xml.encode('utf-8'))
        _HindenWidgetFilter(root)

        xml_with_covered = etree.tostring(root, encoding='unicode')

        view_tree = self.select_target_root_node(xml_with_covered)

        view_tree = self.xml_to_dict(view_tree)

        return view_tree

    def get_views(self) -> List:
        """
        get the view list of the current state
        :return: the view list
        """
        view_tree = self.dump_view()
        if not view_tree:
            return None
        view_tree['parent'] = -1
        view_list = []
        self.__view_tree_to_list(view_tree, view_list)
        self.add_enter_button_from_keyboard_into_view_list(view_list)
        return view_list
    
class _HindenWidgetFilter:
    def __init__(self, root: etree._Element):
        # self.global_drawing_order = 0
        self._nodes = []

        self.idx = rtree.index.Index()
        try:
            self.set_covered_attr(root)
        except Exception as e:
            import traceback, uuid
            traceback.print_exc()
            # logger.error(f"Error in setting covered widgets")
            # from .utils import LoggingLevel
            # if LoggingLevel.level <= logging.DEBUG:
            #     with open(f"kea2_error_tree_{uuid.uuid4().hex}.xml", "wb") as f:
            #         xml_bytes = etree.tostring(root, pretty_print=True, encoding="utf-8", xml_declaration=True)
            #         f.write(xml_bytes)

        # xml_bytes = etree.tostring(root, pretty_print=True, encoding="utf-8", xml_declaration=True)
        # with open("filtered_tree.xml", "wb") as f:
        #     f.write(xml_bytes)
        # # xml_bytes

    def _iter_by_drawing_order(self, ele: etree._Element):
        """
        iter by drawing order (DFS)
        """
        if ele.tag == "node":
            yield ele

        children = list(ele)
        try:
            children.sort(key=lambda e: int(e.get("drawing-order", 0)))
        except (TypeError, ValueError):
            pass

        for child in children:
            yield from self._iter_by_drawing_order(child)
   
    def set_covered_attr(self, root: etree._Element):
        self._nodes: List[etree._Element] = list()
        for e in self._iter_by_drawing_order(root):
            # e.set("global-order", str(self.global_drawing_order))
            # self.global_drawing_order += 1
            e.set("covered", "false")

            # algorithm: filter by "clickable"
            clickable = (e.get("clickable", "false") == "true")
            _raw_bounds = e.get("bounds")
            if _raw_bounds is None:
                continue
            bounds = _get_bounds(_raw_bounds)
            if clickable:
                covered_widget_ids = list(self.idx.contains(bounds))
                if covered_widget_ids:
                    for covered_widget_id in covered_widget_ids:
                        node = self._nodes[covered_widget_id]
                        node.set("covered", "true")
                        self.idx.delete(
                            covered_widget_id,
                            _get_bounds(self._nodes[covered_widget_id].get("bounds"))
                        )

            cur_id = len(self._nodes)
            center = [
                (bounds[0] + bounds[2]) / 2,
                (bounds[1] + bounds[3]) / 2
            ]
            self.idx.insert(
                cur_id,
                (center[0], center[1], center[0], center[1])
            )
            self._nodes.append(e)

def _get_bounds(raw_bounds):
    pattern = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
    m = re.match(pattern, raw_bounds)
    try:
        bounds = [int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))]
    except Exception as e:
        print(f"raw_bounds: {raw_bounds}", flush=True)
        raise RuntimeError(e)

    return bounds


if __name__ == '__main__':
    views = Uiautomator2_Helper().get_views()
    print(views)
