import copy
import hashlib
import json
import logging
import math
import os
import numpy as np
DEBUG_MODE = os.getenv("DEBUG_MODE") == "1"
from .utils import md5
from .input_event import TouchEvent, LongTouchEvent, ScrollEvent, SetTextEvent, KeyEvent, UIEvent


class DeviceState(object):
    """
    the state of the current device
    """

    def __init__(self, device, views, foreground_activity, activity_stack, background_services,
                 tag=None, screenshot_path=None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.device = device
        self.foreground_activity = foreground_activity
        self.activity_stack = activity_stack if isinstance(activity_stack, list) else []
        self.background_services = background_services
        if tag is None:
            from datetime import datetime
            tag = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.tag = tag
        self.screenshot_path = screenshot_path
        self.annotated_screenshot_path = None
        self.views = self.__parse_views(views)
        self.view_tree = {}
        self.__assemble_view_tree(self.view_tree, self.views)
        self.__generate_view_strs()
        self.state_str = self.__get_state_str()
        self.structure_str = self.__get_content_free_state_str()
        self.search_content = self.__get_search_content()
        self.possible_events = None
        self.width = device.get_width(refresh=True)
        self.height = device.get_height(refresh=False)

        self.actionable_widget_list = []
        self.important_widgets = set()
        self.analyze_important_widgets()

    @property
    def activity_short_name(self):
        return self.foreground_activity.split('.')[-1]

    def to_dict(self):
        state = {'tag': self.tag,
                 'state_str': self.state_str,
                 'state_str_content_free': self.structure_str,
                 'foreground_activity': self.foreground_activity,
                 'activity_stack': self.activity_stack,
                 'background_services': self.background_services,
                 'width': self.width,
                 'height': self.height,
                 'views': self.views}
        return state

    def to_json(self):
        import json
        return json.dumps(self.to_dict(), indent=2)

    def __parse_views(self, raw_views):
        views = []
        if not raw_views or len(raw_views) == 0:
            return views

        for view_dict in raw_views:
            # # Simplify resource_id
            # resource_id = view_dict['resource_id']
            # if resource_id is not None and ":" in resource_id:
            #     resource_id = resource_id[(resource_id.find(":") + 1):]
            #     view_dict['resource_id'] = resource_id
            views.append(view_dict)
        return views

    def __assemble_view_tree(self, root_view, views):
        if not len(self.view_tree): # bootstrap
            self.view_tree = copy.deepcopy(views[0])
            self.__assemble_view_tree(self.view_tree, views)
        else:
            children = list(enumerate(root_view["children"]))
            if not len(children):
                return
            for i, j in children:
                root_view["children"][i] = copy.deepcopy(self.views[j])
                self.__assemble_view_tree(root_view["children"][i], views)

    def __generate_view_strs(self):
        for view_dict in self.views:
            self.__get_view_str(view_dict)
            # self.__get_view_structure(view_dict)

    @staticmethod
    def __calculate_depth(views):
        root_view = None
        for view in views:
            if DeviceState.__safe_dict_get(view, 'parent') == -1:
                root_view = view
                break
        DeviceState.__assign_depth(views, root_view, 0)

    @staticmethod
    def __assign_depth(views, view_dict, depth):
        view_dict['depth'] = depth
        for view_id in DeviceState.__safe_dict_get(view_dict, 'children', []):
            DeviceState.__assign_depth(views, views[view_id], depth + 1)

    def __get_state_str(self):
        state_str_raw = self.__get_state_str_raw()
        return md5(state_str_raw)

    def __get_state_str_raw(self):
        if self.device.humanoid is not None:
            import json
            from xmlrpc.client import ServerProxy
            proxy = ServerProxy("http://%s/" % self.device.humanoid)
            return proxy.render_view_tree(json.dumps({
                "view_tree": self.view_tree,
                "screen_res": [self.device.display_info["width"],
                               self.device.display_info["height"]]
            }))
        else:
            view_signatures = set()
            for view in self.views:
                view_signature = DeviceState.__get_view_signature(view)
                if view_signature:
                    view_signatures.add(view_signature)
            return "%s{%s}" % (self.foreground_activity, ",".join(sorted(view_signatures)))

    def __get_content_free_state_str(self):
        if self.device.humanoid is not None:
            import json
            from xmlrpc.client import ServerProxy
            proxy = ServerProxy("http://%s/" % self.device.humanoid)
            state_str = proxy.render_content_free_view_tree(json.dumps({
                "view_tree": self.view_tree,
                "screen_res": [self.device.display_info["width"],
                               self.device.display_info["height"]]
            }))
        else:
            view_signatures = set()
            for view in self.views:
                view_signature = DeviceState.__get_content_free_view_signature(view)
                if view_signature:
                    view_signatures.add(view_signature)
            state_str = "%s{%s}" % (self.foreground_activity, ",".join(sorted(view_signatures)))
        import hashlib
        return hashlib.md5(state_str.encode('utf-8')).hexdigest()

    def __get_search_content(self):
        """
        get a text for searching the state
        :return: str
        """
        words = [",".join(self.__get_property_from_all_views("resource_id")),
                 ",".join(self.__get_property_from_all_views("text"))]
        return "\n".join(words)

    def __get_property_from_all_views(self, property_name):
        """
        get the values of a property from all views
        :return: a list of property values
        """
        property_values = set()
        for view in self.views:
            property_value = DeviceState.__safe_dict_get(view, property_name, None)
            if property_value:
                property_values.add(property_value)
        return property_values

    def save2dir(self, output_dir=None, event=None, phase=None, feature_name=None):
        try:
            if output_dir is None:
                if self.device.output_dir is None:
                    return
                else:
                    output_dir = os.path.join(self.device.output_dir, "states")
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
                
            json_dir = os.path.join(self.device.output_dir, "report_screenshot.json")
            dest_state_json_path = "%s/state_%s.json" % (output_dir, self.tag)
            if self.device.adapters[self.device.minicap]:
                dest_screenshot_path = "%s/screen_%s.jpg" % (output_dir, self.tag)
                img_ext = ".jpg"
            else:
                dest_screenshot_path = "%s/screen_%s.png" % (output_dir, self.tag)
                img_ext = ".png"

            try:
                with open(json_dir, 'r') as json_file:
                    report_screens = json.load(json_file)
            except FileNotFoundError:
                report_screens = []
            
            original_screenshot_path = self.annotated_screenshot_path if self.annotated_screenshot_path else self.screenshot_path

            if original_screenshot_path != dest_screenshot_path:
                state_json_file = open(dest_state_json_path, "w")
                state_json_file.write(self.to_json())
                state_json_file.close()
                import shutil

                shutil.copyfile(original_screenshot_path, dest_screenshot_path)
                report_screen = {
                    "event": "",
                    "event_index": str(self.tag),
                    "screen_shoot": "screen_" + str(self.tag) + img_ext,
                    "phase": phase if phase else "",
                    "feature": feature_name if feature_name else ""
                }
                report_screens.append(report_screen)

            if event is not None:
                self.draw_event(event, dest_screenshot_path)
                report_screens[-1]["event"] = event.get_event_name()
                if phase:
                    report_screens[-1]["phase"] = phase
                if feature_name:
                    report_screens[-1]["feature"] = feature_name
            with open(json_dir, 'w') as json_file:
                json.dump(report_screens, json_file, indent=4)
            # Incremental report append for this entry
            try:
                from . import utils as _utils
                if report_screens:
                    _utils.append_incremental_report_item(output_dir, self.device.output_dir, report_screens[-1])
            except Exception:
                self.logger.error("Failed to append incremental report item.")
                pass
            # self.screenshot_path = dest_screenshot_path
            # from PIL.Image import Image
            # if isinstance(self.screenshot_path, Image):
            #     self.screenshot_path.save(dest_screenshot_path)
        except Exception as e:
            self.device.logger.warning(e)
    
    def draw_event(self, event, screenshot_path):
        import cv2
        image = cv2.imread(screenshot_path)
        if event is not None and screenshot_path is not None:
            if isinstance(event, TouchEvent):
                cv2.rectangle(image, (int(event.view['bounds'][0][0]),int(event.view['bounds'][0][1])),(int(event.view['bounds'][1][0]),int(event.view['bounds'][1][1])), (0, 0, 255), 5)
            elif isinstance(event, LongTouchEvent):
                cv2.rectangle(image, (int(event.view['bounds'][0][0]),int(event.view['bounds'][0][1])),(int(event.view['bounds'][1][0]),int(event.view['bounds'][1][1])), (0, 255, 0), 5)
            elif isinstance(event, SetTextEvent):
                cv2.rectangle(image, (int(event.view['bounds'][0][0]),int(event.view['bounds'][0][1])),(int(event.view['bounds'][1][0]),int(event.view['bounds'][1][1])), (255, 0, 0), 5)
            elif isinstance(event, ScrollEvent):
                cv2.rectangle(image, (int(event.view['bounds'][0][0]),int(event.view['bounds'][0][1])),(int(event.view['bounds'][1][0]),int(event.view['bounds'][1][1])), (255, 255, 0), 5)
            elif isinstance(event, KeyEvent):
                cv2.putText(image,event.name, (100,300), cv2.FONT_HERSHEY_SIMPLEX, 5,(0, 255, 0), 3, cv2.LINE_AA)
            else:
                return
            try:
                cv2.imwrite(screenshot_path, image)
            except Exception as e:
                self.logger.warning(e)  

    def get_state_screen(self): 
        return self.screenshot_path

    def save_view_img(self, view_dict, output_dir=None):
        try:
            if output_dir is None:
                if self.device.output_dir is None:
                    return
                else:
                    output_dir = os.path.join(self.device.output_dir, "views")
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
            view_str = view_dict['view_str']
            if self.device.adapters[self.device.minicap]:
                view_file_path = "%s/view_%s.jpg" % (output_dir, view_str)
            else:
                view_file_path = "%s/view_%s.png" % (output_dir, view_str)
            if os.path.exists(view_file_path):
                return
            from PIL import Image
            # Load the original image:
            view_bound = view_dict['bounds']
            original_img = Image.open(self.screenshot_path)
            # view bound should be in original image bound
            view_img = original_img.crop((min(original_img.width - 1, max(0, view_bound[0][0])),
                                          min(original_img.height - 1, max(0, view_bound[0][1])),
                                          min(original_img.width, max(0, view_bound[1][0])),
                                          min(original_img.height, max(0, view_bound[1][1]))))
            view_img.convert("RGB").save(view_file_path)
        except Exception as e:
            self.device.logger.warning(e)

    def is_different_from(self, another_state):
        """
        compare this state with another
        @param another_state: DeviceState
        @return: boolean, true if this state is different from other_state
        """
        return self.state_str != another_state.state_str

    @staticmethod
    def __get_view_signature(view_dict):
        """
        get the signature of the given view
        @param view_dict: dict, an element of list DeviceState.views
        @return:
        """
        if 'signature' in view_dict:
            return view_dict['signature']

        view_text = DeviceState.__safe_dict_get(view_dict, 'text', "None")
        if view_text is None or len(view_text) > 50:
            view_text = "None"

        signature = "[class]%s[resource_id]%s[text]%s[%s,%s,%s]" % \
                    (DeviceState.__safe_dict_get(view_dict, 'class', "None"),
                     DeviceState.__safe_dict_get(view_dict, 'resource_id', "None"),
                     view_text,
                     DeviceState.__key_if_true(view_dict, 'enabled'),
                     DeviceState.__key_if_true(view_dict, 'checked'),
                     DeviceState.__key_if_true(view_dict, 'selected'))
        view_dict['signature'] = signature
        return signature

    @staticmethod
    def __get_content_free_view_signature(view_dict):
        """
        get the content-free signature of the given view
        @param view_dict: dict, an element of list DeviceState.views
        @return:
        """
        if 'content_free_signature' in view_dict:
            return view_dict['content_free_signature']
        content_free_signature = "[class]%s[resource_id]%s" % \
                                 (DeviceState.__safe_dict_get(view_dict, 'class', "None"),
                                  DeviceState.__safe_dict_get(view_dict, 'resource_id', "None"))
        view_dict['content_free_signature'] = content_free_signature
        return content_free_signature

    def __get_view_str(self, view_dict):
        """
        get a string which can represent the given view
        @param view_dict: dict, an element of list DeviceState.views
        @return:
        """
        if 'view_str' in view_dict:
            return view_dict['view_str']
        view_signature = DeviceState.__get_view_signature(view_dict)
        parent_strs = []
        for parent_id in self.get_all_ancestors(view_dict):
            parent_strs.append(DeviceState.__get_view_signature(self.views[parent_id]))
        parent_strs.reverse()
        child_strs = []
        for child_id in self.get_all_children(view_dict):
            child_strs.append(DeviceState.__get_view_signature(self.views[child_id]))
        child_strs.sort()
        view_str = "Activity:%s\nSelf:%s\nParents:%s\nChildren:%s" % \
                   (self.foreground_activity, view_signature, "//".join(parent_strs), "||".join(child_strs))
        import hashlib
        view_str = hashlib.md5(view_str.encode('utf-8')).hexdigest()
        view_dict['view_str'] = view_str
        return view_str

    def __get_view_structure(self, view_dict):
        """
        get the structure of the given view
        :param view_dict: dict, an element of list DeviceState.views
        :return: dict, representing the view structure
        """
        if 'view_structure' in view_dict:
            return view_dict['view_structure']
        width = DeviceState.get_view_width(view_dict)
        height = DeviceState.get_view_height(view_dict)
        class_name = DeviceState.__safe_dict_get(view_dict, 'class', "None")
        children = {}

        root_x = view_dict['bounds'][0][0]
        root_y = view_dict['bounds'][0][1]

        child_view_ids = self.__safe_dict_get(view_dict, 'children')
        if child_view_ids:
            for child_view_id in child_view_ids:
                child_view = self.views[child_view_id]
                child_x = child_view['bounds'][0][0]
                child_y = child_view['bounds'][0][1]
                relative_x, relative_y = child_x - root_x, child_y - root_y
                children["(%d,%d)" % (relative_x, relative_y)] = self.__get_view_structure(child_view)

        view_structure = {
            "%s(%d*%d)" % (class_name, width, height): children
        }
        view_dict['view_structure'] = view_structure
        return view_structure
    def get_important_view_hash(self, view_dict):
        """
       
        :param view_dict: dict, an element of list DeviceState.views
        :return: str
        """
        if 'important_view_str' in view_dict:
            return view_dict['important_view_str']
        raw_string = ""
        raw_string += self.foreground_activity.split('.')[-1]
        important_keys = [
            ('class', 'class'),
            ('resource_id', 'resource_id'),
            ('text', 'text'),
            ('description', 'content_description'),
        ]
        for output_key, source_key in important_keys:
            value = DeviceState.__safe_dict_get(view_dict, source_key, "None")
            if source_key == 'text' and value is not None:
                if value in self.device.valid_texts:
                    raw_string += "[%s]%s" % (output_key, value)
                    continue
                else:
                    value = "None"
            raw_string += "[%s]%s" % (output_key, value)
        view_dict['important_view_str'] = raw_string
        return raw_string
    
    def get_important_view_hash_with_text(self, view_dict):
        """
       
        :param view_dict: dict, an element of list DeviceState.views
        :return: str
        """
        # if 'important_view_str' in view_dict:
        #     return view_dict['important_view_str']
        raw_string = ""
        raw_string += self.foreground_activity.split('.')[-1]
        important_keys = [
            ('class', 'class'),
            ('resource_id', 'resource_id'),
            ('text', 'text'),
            ('description', 'content_description'),
        ]
        for output_key, source_key in important_keys:
            value = DeviceState.__safe_dict_get(view_dict, source_key, "None")
            raw_string += "[%s]%s" % (output_key, value)
        # view_dict['important_view_str'] = raw_string
        return raw_string

    @staticmethod
    def __key_if_true(view_dict, key):
        return key if (key in view_dict and view_dict[key]) else ""

    @staticmethod
    def __safe_dict_get(view_dict, key, default=None):
        return view_dict[key] if (key in view_dict) else default

    @staticmethod
    def get_view_center(view_dict):
        """
        return the center point in a view
        @param view_dict: dict, an element of DeviceState.views
        @return: a pair of int
        """
        bounds = view_dict['bounds']
        return (bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2

    @staticmethod
    def get_view_width(view_dict):
        """
        return the width of a view
        @param view_dict: dict, an element of DeviceState.views
        @return: int
        """
        bounds = view_dict['bounds']
        return int(math.fabs(bounds[0][0] - bounds[1][0]))

    @staticmethod
    def get_view_height(view_dict):
        """
        return the height of a view
        @param view_dict: dict, an element of DeviceState.views
        @return: int
        """
        bounds = view_dict['bounds']
        return int(math.fabs(bounds[0][1] - bounds[1][1]))

    def get_all_ancestors(self, view_dict):
        """
        Get temp view ids of the given view's ancestors
        :param view_dict: dict, an element of DeviceState.views
        :return: list of int, each int is an ancestor node id
        """
        result = []
        parent_id = self.__safe_dict_get(view_dict, 'parent', -1)
        if 0 <= parent_id < len(self.views):
            result.append(parent_id)
            result += self.get_all_ancestors(self.views[parent_id])
        return result

    def get_all_children(self, view_dict):
        """
        Get temp view ids of the given view's children
        :param view_dict: dict, an element of DeviceState.views
        :return: set of int, each int is a child node id
        """
        children = self.__safe_dict_get(view_dict, 'children')
        if not children:
            return set()
        children = set(children)
        for child in children:
            children_of_child = self.get_all_children(self.views[child])
            children.union(children_of_child)
        return children

    def get_app_activity_depth(self, app):
        """
        Get the depth of the app's activity in the activity stack
        :param app: App
        :return: the depth of app's activity, -1 for not found
        """
        depth = 0
        for activity_str in self.activity_stack:
            if app.package_name in activity_str:
                return depth
            depth += 1
        return -1

    def get_possible_input(self):
        """
        Get a list of possible input events for this state
        :return: list of InputEvent
        """
        if self.possible_events:
            return [] + self.possible_events
        possible_events = []
        enabled_view_ids = []
        touch_exclude_view_ids = set()
        for view_dict in self.views:
            # exclude navigation bar if exists
            if self.__safe_dict_get(view_dict, 'enabled') and \
                    self.__safe_dict_get(view_dict, 'visible') and \
                    self.__safe_dict_get(view_dict, 'resource_id') not in \
               ['android:id/navigationBarBackground',
                'android:id/statusBarBackground']:
                enabled_view_ids.append(view_dict['temp_id'])
        # enabled_view_ids.reverse()

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'clickable'):
                possible_events.append(TouchEvent(view=self.views[view_id]))
                touch_exclude_view_ids.add(view_id)
                touch_exclude_view_ids.union(self.get_all_children(self.views[view_id]))

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'scrollable'):
                possible_events.append(ScrollEvent(view=self.views[view_id], direction="UP"))
                possible_events.append(ScrollEvent(view=self.views[view_id], direction="DOWN"))
                possible_events.append(ScrollEvent(view=self.views[view_id], direction="LEFT"))
                possible_events.append(ScrollEvent(view=self.views[view_id], direction="RIGHT"))

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'checkable'):
                possible_events.append(TouchEvent(view=self.views[view_id]))
                touch_exclude_view_ids.add(view_id)
                touch_exclude_view_ids.union(self.get_all_children(self.views[view_id]))

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'long_clickable'):
                possible_events.append(LongTouchEvent(view=self.views[view_id]))

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'editable'):
                possible_events.append(SetTextEvent(view=self.views[view_id], text="HelloWorld"))
                touch_exclude_view_ids.add(view_id)
                # TODO figure out what event can be sent to editable views
                # pass

        for view_id in enabled_view_ids:
            if view_id in touch_exclude_view_ids:
                continue
            children = self.__safe_dict_get(self.views[view_id], 'children')
            if children and len(children) > 0:
                continue
            possible_events.append(TouchEvent(view=self.views[view_id]))

        # For old Android navigation bars
        # possible_events.append(KeyEvent(name="MENU"))

        self.possible_events = possible_events
        return [] + possible_events
    
    def _get_self_ancestors_property(self, view, key, default=None):
        all_views = [view] + [self.views[i] for i in self.get_all_ancestors(view)]
        for v in all_views:
            value = self.__safe_dict_get(v, key)
            if value:
                return value
        return default
    
    def get_described_actions(self):
        """
        Get a text description of current state
        """
        enabled_view_ids = []
        for view_dict in self.views:
            # exclude navigation bar if exists
            if self.__safe_dict_get(view_dict, 'visible') and \
                self.__safe_dict_get(view_dict, 'resource_id') not in \
               ['android:id/navigationBarBackground',
                'android:id/statusBarBackground']:
                enabled_view_ids.append(view_dict['temp_id'])

        view_descs = []
        available_actions = []
        for view_id in enabled_view_ids:
            view = self.views[view_id]
            clickable = self._get_self_ancestors_property(view, 'clickable')
            scrollable = self.__safe_dict_get(view, 'scrollable')
            checkable = self._get_self_ancestors_property(view, 'checkable')
            long_clickable = self._get_self_ancestors_property(view, 'long_clickable')
            editable = self.__safe_dict_get(view, 'editable')
            actionable = clickable or scrollable or checkable or long_clickable or editable
            checked = self.__safe_dict_get(view, 'checked')
            selected = self.__safe_dict_get(view, 'selected')
            content_description = self.__safe_dict_get(view, 'content_description', default='')
            view_text = self.__safe_dict_get(view, 'text', default='')
            if not content_description and not view_text and not scrollable and not actionable:  # actionable?
                continue
            
            view_status = ''
            if editable:
                view_status += 'editable '
            if checked or selected:
                view_status += 'checked '
            view_desc = f'- a {view_status}view'
            if content_description:
                content_description = content_description.replace('\n', '  ')
                content_description = f'{content_description[:20]}...' if len(content_description) > 20 else content_description
                view_desc += f' "desc={content_description}"'
            if view_text:
                view_text = view_text.replace('\n', '  ')
                view_text = f'{view_text[:20]}...' if len(view_text) > 20 else view_text
                view_desc += f' with text "{view_text}"'
            if actionable:
                view_actions = []
                if editable:
                    view_actions.append(f'edit ({len(available_actions)})')
                    available_actions.append(SetTextEvent(view=view, text='HelloWorld'))
                if clickable or checkable:
                    view_actions.append(f'click ({len(available_actions)})')
                    available_actions.append(TouchEvent(view=view))
                # if checkable:
                #     view_actions.append(f'check/uncheck ({len(available_actions)})')
                #     available_actions.append(TouchEvent(view=view))
                # if long_clickable:
                #     view_actions.append(f'long click ({len(available_actions)})')
                #     available_actions.append(LongTouchEvent(view=view))
                if scrollable:
                    view_actions.append(f'scroll up ({len(available_actions)})')
                    available_actions.append(ScrollEvent(view=view, direction='UP'))
                    view_actions.append(f'scroll down ({len(available_actions)})')
                    available_actions.append(ScrollEvent(view=view, direction='DOWN'))
                view_actions_str = ', '.join(view_actions)
                view_desc += f' that can {view_actions_str}'
            view_descs.append(view_desc)
        view_descs.append(f'- a key to go back ({len(available_actions)})')
        available_actions.append(KeyEvent(name='BACK'))
        state_desc = 'The current state has the following UI views and corresponding actions, with action id in parentheses:\n '
        state_desc += ';\n '.join(view_descs)
        return state_desc, available_actions
    
    def get_view_desc(self, view):
        content_description = self.__safe_dict_get(view, 'content_description', default='')
        view_text = self.__safe_dict_get(view, 'text', default='')
        scrollable = self.__safe_dict_get(view, 'scrollable')
        view_desc = f'view'
        if scrollable:
            view_desc = f'scrollable view'
        if content_description:
            view_desc += f' "{content_description}"'
        if view_text:
            view_text = view_text.replace('\n', '  ')
            view_text = f'{view_text[:20]}...' if len(view_text) > 20 else view_text
            view_desc += f' with text "{view_text}"'
        return view_desc
    
    def get_candidate_actions(self):
        """
        Get a list of candidate actions for this state
        :return: list of InputEvent
        """
        if self.possible_events:
            return [] + self.possible_events
        possible_events = []
        enabled_view_ids = []
        touch_exclude_view_ids = set()
        for view_dict in self.views:
            # exclude navigation bar if exists
            if self.__safe_dict_get(view_dict, 'enabled') and \
                    self.__safe_dict_get(view_dict, 'visible') and \
                    self.__safe_dict_get(view_dict, 'resource_id') not in \
               ['android:id/navigationBarBackground',
                'android:id/statusBarBackground']:
                enabled_view_ids.append(view_dict['temp_id'])
        enabled_view_ids.reverse()

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'clickable') and not (
                '.widget.EditText' in self.__safe_dict_get(self.views[view_id], 'class')):
                possible_events.append(TouchEvent(view=self.views[view_id]))
                touch_exclude_view_ids.add(view_id)
                touch_exclude_view_ids.union(self.get_all_children(self.views[view_id]))

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'scrollable'):
                possible_events.append(ScrollEvent(view=self.views[view_id], direction="UP"))
                possible_events.append(ScrollEvent(view=self.views[view_id], direction="DOWN"))
                possible_events.append(ScrollEvent(view=self.views[view_id], direction="LEFT"))
                possible_events.append(ScrollEvent(view=self.views[view_id], direction="RIGHT"))

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'checkable'):
                possible_events.append(TouchEvent(view=self.views[view_id]))
                touch_exclude_view_ids.add(view_id)
                touch_exclude_view_ids.union(self.get_all_children(self.views[view_id]))

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'long_clickable') and not self.__safe_dict_get(self.views[view_id], 'class') == 'android.widget.EditText':
                possible_events.append(LongTouchEvent(view=self.views[view_id]))

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'editable'):
                possible_events.append(SetTextEvent(view=self.views[view_id], text=""))
                touch_exclude_view_ids.add(view_id)
                # TODO figure out what event can be sent to editable views
                pass

        for view_id in enabled_view_ids:
            if view_id in touch_exclude_view_ids:
                continue
            children = self.__safe_dict_get(self.views[view_id], 'children')
            if children and len(children) > 0:
                continue
            possible_events.append(TouchEvent(view=self.views[view_id]))

        # For old Android navigation bars
        # possible_events.append(KeyEvent(name="MENU"))

        self.possible_events = possible_events
        return [] + possible_events
        
    def get_action_desc(self, action):
        desc = action.event_type
        if isinstance(action, KeyEvent):
            desc = f'- go {action.name.lower()}'
        if isinstance(action, UIEvent):
            action_name = action.event_type
            if isinstance(action, LongTouchEvent):
                action_name = 'long click'
            elif isinstance(action, SetTextEvent):
                action_name = f'enter "{action.text}" into'
            elif isinstance(action, ScrollEvent):
                action_name = f'scroll {action.direction.lower()}'
            desc = f'- {action_name} {self.get_view_desc(action.view)}'
        return desc
    
    def get_action_dsl(self, action):
        if isinstance(action, TouchEvent):
            if action.view["resource_id"]:
                return f'click(id="{action.view["resource_id"]}")'
            elif action.view["text"]:
                return f'click(text="{action.view["text"]}")'
            elif action.view["content_description"]:
                return f'click(desc="{action.view["content_description"]}")'
            elif action.view["class"]:
                return f'click(class="{action.view["class"]}")'
        elif isinstance(action, LongTouchEvent):
            if action.view["resource_id"]:
                return f'long_click(id="{action.view["resource_id"]}")'
            elif action.view["text"]:
                return f'long_click(text="{action.view["text"]}")'
            elif action.view["content_description"]:
                return f'long_click(desc="{action.view["content_description"]}")'
            elif action.view["class"]:
                return f'long_click(class="{action.view["class"]}")'
        elif isinstance(action, SetTextEvent):
            if action.view["resource_id"]:
                return f'set_text(id="{action.view["resource_id"]}", input="{action.text}")'
            elif action.view["text"]:
                return f'set_text(text="{action.view["text"]}", input="{action.text}")'
            elif action.view["content_description"]:
                return f'set_text(desc="{action.view["content_description"]}", input="{action.text}")'
            elif action.view["class"]:
                return f'set_text(class="{action.view["class"]}", input="{action.text}")'
        elif isinstance(action, KeyEvent):
            return f'press_key("{action.name}")'
        else:
            raise NotImplementedError
            
    def find_widget(self, key: str, value: str):
        for view in self.views:
            if key == "id" and self.__safe_dict_get(view, "resource_id") == value:
                return view
            if key == "text" and self.__safe_dict_get(view, "text") == value:
                return view
            if key == "desc" and self.__safe_dict_get(view, "content_description") == value:
                return view
            if key == "class" and self.__safe_dict_get(view, "class") == value:
                return view
        return None

    def get_actionable_widget_list(self, failed_widgets=None):
        if self.actionable_widget_list and failed_widgets is None:
            return self.actionable_widget_list
        
        actionable_widgets = []
        enabled_view_ids = []
        
        for view_dict in self.views:
            # exclude navigation bar if exists
            if self.__safe_dict_get(view_dict, 'enabled') and \
                    self.__safe_dict_get(view_dict, 'visible') and \
                    self.__safe_dict_get(view_dict, 'resource_id') not in \
               ['android:id/navigationBarBackground',
                'android:id/statusBarBackground']:
                enabled_view_ids.append(view_dict['temp_id'])
        enabled_view_ids.reverse()

        for view_id in enabled_view_ids:

            children = self.__safe_dict_get(self.views[view_id], 'children')
            if children and len(children) > 0:
                continue
            if self.__safe_dict_get(self.views[view_id], 'covered'):
                continue
            if failed_widgets:
                is_skip = False
                for failed_widget in failed_widgets:
                    if self.__safe_dict_get(self.views[view_id], 'view_str') == \
                        self.__safe_dict_get(failed_widget, 'view_str'):
                        is_skip = True
                        break
                if is_skip:
                    if DEBUG_MODE:
                        self.logger.info(f"Skip annotating failed widget: {self.views[view_id]}")
                    continue
            include_class_list = ['android.widget.ImageView', 'android.widget.Button', 'android.widget.ImageButton', 'android.widget.EditText', 'android.widget.CheckBox', 'android.widget.RadioButton', 'android.widget.Switch',
            "com.google.android.material.floatingactionbutton.FloatingActionButton"]
            if self.__safe_dict_get(self.views[view_id], 'text') or \
                self.__safe_dict_get(self.views[view_id], 'content_description') or \
                self.__safe_dict_get(self.views[view_id], 'class') in include_class_list:
                width = self.get_view_width(self.views[view_id])
                height = self.get_view_height(self.views[view_id])
                if width < 5 or height < 5:
                    continue

                is_overlap_with_existing = False
                for widget in actionable_widgets:
                    if self.whether_the_widget_overlap(self.views[view_id], widget):
                        is_overlap_with_existing = True
                        break
                if not is_overlap_with_existing:
                    actionable_widgets.append(self.views[view_id])
            
        self.actionable_widget_list = actionable_widgets 
        return actionable_widgets

    def whether_the_widget_overlap(self, widget1, widget2):
        center_1 = self.get_view_center(widget1)
        center_2 = self.get_view_center(widget2)
        dist = (abs(center_1[0] - center_2[0]) ** 2 + abs(center_1[1] - center_2[1]) ** 2) ** 0.5
        if dist < 30:
            return True
        return False
    
    def generate_annotated_screenshot(self,  failed_widgets=None,dark_mode=False):
        if self.annotated_screenshot_path and os.path.exists(self.annotated_screenshot_path):
            return self.annotated_screenshot_path
        actionable_widgets = self.get_actionable_widget_list(failed_widgets)
        screenshot = self.screenshot_path
        annotated_screenshot_path = screenshot.replace("screen_", "annotated_screen_")
        import cv2
        import pyshine as ps
        image = cv2.imread(screenshot)
        if image is None:
            return screenshot
        if not actionable_widgets:
            cv2.imwrite(annotated_screenshot_path, image)
            self.annotated_screenshot_path = annotated_screenshot_path
            return annotated_screenshot_path
        annotated_screenshot = image.copy()
        colors = [(0, 122, 255),
                   (255, 45, 85),
                     (52, 199, 89),
                       (255, 149, 0),
                         (175, 82, 222),
                           (255, 204, 0),
                             (90, 200, 250),
                               (88, 86, 214)]
        
        for index, widget in enumerate(actionable_widgets):
            bounds = widget.get('bounds')
            if not bounds or len(bounds) != 2 or len(bounds[0]) != 2 or len(bounds[1]) != 2:
                continue
            x1, y1 = int(bounds[0][0]), int(bounds[0][1])
            x2, y2 = int(bounds[1][0]), int(bounds[1][1])
            color = colors[index % len(colors)]
            cv2.rectangle(annotated_screenshot, (x1, y1), (x2, y2), color[::-1], 2)

            # Calculate label position so it sits at the widget's top-right corner
            # Use cv2.getTextSize to estimate the rendered text size (width, height)
            label = str(index + 1)
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.9
            thickness = 2
            (text_w, text_h), baseline = cv2.getTextSize(label, font, font_scale, thickness)

            # Desired top-right corner of label: a few pixels inside widget's top-right
            desired_x = x2 - 4  # 4px padding from widget right edge
            desired_y = y1 + 6  # place text just below the top edge with small padding

            # Ensure the label background and text do not go outside the image bounds
            img_h, img_w = annotated_screenshot.shape[0], annotated_screenshot.shape[1]

            # The putBText uses text_offset as the bottom-left corner of the text block in OpenCV coords
            # so compute bottom-left x,y for the text such that the text's top-right is near desired coords
            text_x = desired_x - text_w
            text_y = desired_y

            # Clamp to image bounds
            text_x = max(0, min(text_x, img_w - text_w))
            text_y = max(text_h, min(text_y, img_h - baseline))

            try:
                annotated_screenshot = ps.putBText(
                    annotated_screenshot.copy(),
                    label,
                    text_offset_x=int(text_x),
                    text_offset_y=int(text_y),
                    vspace=6,
                    hspace=3,
                    font_scale=font_scale,
                    thickness=thickness,
                    background_RGB=color,
                    text_RGB=(255, 250, 250),
                    alpha=0.5
                )
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.logger.warning(f"Failed to annotate widget {index+1}: {e}")
                continue
        cv2.imwrite(annotated_screenshot_path, annotated_screenshot)
        self.annotated_screenshot_path = annotated_screenshot_path
        return annotated_screenshot_path

    # def getVector(self):

    #     vector_str = ""
    #     child_stack = []
        
    #     root = ""
    #     root = self.views[0]
    #     child_stack.append(root)
    #     # print(root.attrib)
    #     # for child in root:
    #     #     # print(child.tag, child.attrib)
    #     #     if child.attrib['package'] == project.used_name:
    #     #         child_stack.append(child)

    #     while len(child_stack) > 0:
    #         m = hashlib.md5()
    #         node = child_stack.pop()
    #         res_id = self.__safe_dict_get(node, "resource_id", "NO_ID")
    #         class_name = self.__safe_dict_get(node, "class", "NO_CLASS")
    #         text = self.__safe_dict_get(node, "text", "")
    #         package_name = self.__safe_dict_get(node, "package", "package")
    #         # is_clickable = self.__safe_dict_get(node, "clickable", False)

            
    #         if class_name != "android.widget.FrameLayout":
    #             #tmpstr = res_id + class_name + package_name 
    #             tmpstr = f"{res_id}|{class_name}|{package_name}"
    #             m.update(tmpstr.encode("utf8"))
    #             vector_str = vector_str + m.hexdigest()
    #         elif class_name == "android.widget.FrameLayout":
    #             if len(node.get("children", [])) != 0:
    #             #if not root[0] == None and not root[0]:
    #                 tmpstr = f"{res_id}|{class_name}|{package_name}"
    #                 m.update(tmpstr.encode("utf8"))
    #                 vector_str = vector_str + m.hexdigest()
    #         if class_name == "android.widget.ListView":
    #             if len(node.get("children", [])) != 0:
    #                 child_stack.append(self.views[node.get("children", [])[0]])
    #         else:
    #             for child in node.get("children", [])[::-1]:
    #                 child = self.views[child]
    #                 child_stack.append(child)
    #     vector = hashlib.md5()
    #     vector.update(vector_str.encode("utf8"))
    #     return vector.hexdigest()
    
    def analyze_important_widgets(self):

         actionable_widgets = self.get_actionable_widget_list()
         for widget in actionable_widgets:
             if self.__safe_dict_get(widget, "package", "package") != self.device.app.package_name:
                 continue
             important_str = self.get_important_view_hash(widget)
             self.important_widgets.add(important_str)
            
            
    def get_leaf_views_signature_list(self):
        leaf_view_signatures = []
        for view in self.views:
            children = self.__safe_dict_get(view, 'children')
            if not children or len(children) == 0:
                signature = self.get_important_view_hash_with_text(view)
                leaf_view_signatures.append(signature)
        return leaf_view_signatures
