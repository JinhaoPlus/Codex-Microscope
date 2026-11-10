"""Presentation keys for local icons. Labels and execution status are independent."""
KIND = {
    'read': 'BookOpen', 'list_files': 'FolderOpen', 'search': 'Search', 'edit': 'Edit',
    'image': 'Image', 'web': 'Globe', 'run': 'Terminal', 'session': 'Terminal',
    'agent': 'Users', 'browser': 'Monitor',
}
TOOLS = {
    'clock.sleep': 'Timer', 'clock__sleep': 'Timer', 'clock__curr_time': 'Clock',
    'update_plan': 'ListChecks', 'create_goal': 'Target', 'update_goal': 'Target', 'get_goal': 'Target',
    'request_user_input': 'MessageCircleQuestion', 'request_user_input_async': 'MessageCircleQuestion',
    'spawn_agent': 'UserPlus', 'followup_task': 'ListPlus', 'send_message': 'Send',
    'list_agents': 'Users', 'wait_agent': 'Hourglass', 'interrupt_agent': 'CircleStop',
    'list_mcp_resources': 'Files', 'list_mcp_resource_templates': 'Files', 'read_mcp_resource': 'FileText',
    'apply_patch': 'FileDiff', 'view_image': 'Image',
}
WEB = {
    'search_query':'Search', 'search':'Search', 'open':'Globe', 'openPage':'Globe', 'click':'Link',
    'find':'FileSearch', 'findInPage':'FileSearch', 'image_query':'Image', 'screenshot':'Scan',
}

def combine(icons, mixed='Layers'):
    distinct=set(icons)
    if len(distinct)==1:
        return distinct.pop()
    return mixed if distinct else 'Tools'

def file_action(action):
    if action.get('type')=='edit':
        if action.get('old_path'):
            return 'MoveRight'
        return {'add':'FilePlus','delete':'FileMinus'}.get(action.get('change'),'Edit')
    return KIND.get(action.get('type'),'Terminal')

def terminal_input(chars):
    if not isinstance(chars,str):
        return 'Terminal'
    if not chars:
        return 'Hourglass'
    return 'CircleStop' if chars=='\x03' else 'Keyboard'

def operation(op):
    tool=(op.get('tool') or '').removeprefix('functions.').removeprefix('collaboration.')
    args=op.get('arguments') if isinstance(op.get('arguments'),dict) else {}
    event=op.get('event') or {}
    family=event.get('native_family')
    if family=='agent_activity':
        return {'started':'UserPlus','interacted':'Send','completed':'UserCheck','interrupted':'CircleStop'}.get(event.get('kind'),'Users')
    if family=='dynamic':
        return 'Plug'
    if tool in ('web.run','web__run','mcp__codex_apps__search_service_web_run'):
        native=(event.get('action') or {}).get('type')
        if native in WEB:
            return WEB[native]
        icons=[icon for key,icon in WEB.items() if args.get(key)]
        return combine(icons,'Globe') if icons else 'Globe'
    if tool in ('image_gen__imagegen','image_gen.imagegen'):
        editing=args.get('referenced_image_paths') or args.get('num_last_images_to_include')
        return 'Brush' if editing else 'ImagePlus'
    if tool=='write_stdin':
        return terminal_input(args.get('chars','') if isinstance(op.get('arguments'),dict) else None)
    if tool=='wait':
        return 'CircleStop' if args.get('terminate') is True else 'Hourglass'
    if tool in TOOLS:
        return TOOLS[tool]
    if op.get('kind')=='browser':
        return 'Monitor'
    if tool.startswith('mcp__'):
        return 'Plug'
    if not tool and 'sourceIndex' not in op and 'script' in op.get('evidence',[]):
        return 'Code'
    return KIND.get(op.get('kind'),'Tools')
