import unittest

import server
from tool_icons import operation


class ToolIcons(unittest.TestCase):
    def test_summary_and_details_agree_for_direct_nested_and_native_calls(self):
        cases={
            'clock':['Clock','Timer','Timer'],
            'cell-image':['ImagePlus','Hourglass','Hourglass'],
            'view-error':['Image'], 'native-image':['Image'], 'generation-error':['Brush'],
            'terminal':['Terminal','Hourglass','Keyboard','CircleStop'],
            'quiet-poll':['Hourglass','Hourglass'], 'native-agents':['UserPlus','Hourglass','UserCheck'],
            'parallel-image':['Layers'], 'database-actions':['Layers'], 'patch':['FileDiff'],
        }
        for case, expected in cases.items():
            with self.subTest(case=case):
                query={'id':[case]}
                page=server.demo_response('/api/demo/thread',query)[1]
                items=[i for i in page['items'] if i['kind']=='tool']
                icons=[(i.get('exec_view') or i['operations'][0])['icon'] for i in items]
                self.assertEqual(icons,expected)
                for i,icon in zip(items,icons):
                    detail=server.demo_response('/api/demo/thread',{**query,'item':[str(i['index'])]})[1]['item']
                    self.assertEqual((detail.get('exec_view') or detail['operations'][0])['icon'],icon)
                    if case=='patch':
                        self.assertEqual(detail['exec_view']['rows'][0]['action_icons'],['FilePlus','MoveRight','FileMinus'])

    def test_unknown_tools_do_not_borrow_an_icon_from_a_title_or_result(self):
        self.assertEqual(operation({'tool':'mcp__demo__render','arguments':{'title':'sleep image'},'kind':'other'}),'Plug')
        self.assertEqual(operation({'tool':'unrecognized','arguments':{'path':'photo.png'},'kind':'other'}),'Tools')
