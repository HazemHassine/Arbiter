import os
import re

# Lucide to Radix mapping
ICON_MAP = {
    "Activity": "ActivityLogIcon",
    "AlertTriangle": "ExclamationTriangleIcon",
    "ArrowRight": "ArrowRightIcon",
    "Bot": "TargetIcon", 
    "Box": "CubeIcon",
    "Brain": "LightningBoltIcon",
    "Check": "CheckIcon",
    "CircleHelp": "QuestionMarkCircledIcon",
    "Clock3": "ClockIcon",
    "Container": "BoxIcon",
    "ContainerIcon": "BoxIcon",
    "Copy": "CopyIcon",
    "Cpu": "DesktopIcon",
    "Database": "ArchiveIcon",
    "ExternalLink": "ExternalLinkIcon",
    "FileCode2": "CodeIcon",
    "FileText": "FileTextIcon",
    "Focus": "Crosshair2Icon",
    "Folder": "Link2Icon",
    "FolderKanban": "LayersIcon",
    "Gauge": "DashboardIcon",
    "HardDrive": "DiscIcon",
    "History": "UpdateIcon",
    "Maximize2": "SizeIcon",
    "Network": "Share2Icon",
    "Pause": "PauseIcon",
    "Play": "PlayIcon",
    "Radio": "RadiobuttonIcon",
    "RefreshCw": "ReloadIcon",
    "RotateCcw": "ResetIcon",
    "Route": "MagnifyingGlassIcon", # using magnifying glass if route unavailable
    "Save": "CheckIcon",
    "ScanSearch": "MagnifyingGlassIcon",
    "Search": "MagnifyingGlassIcon",
    "Server": "CubeIcon",
    "Settings2": "GearIcon",
    "ShieldAlert": "ExclamationTriangleIcon",
    "ShieldCheck": "LockClosedIcon",
    "Sparkles": "StarIcon",
    "Square": "SquareIcon",
    "Terminal": "CodeIcon",
    "Trash2": "TrashIcon",
    "WandSparkles": "MagicWandIcon",
    "Wrench": "MixerHorizontalIcon",
    "X": "Cross2Icon",
    "ZoomIn": "ZoomInIcon",
    "ZoomOut": "ZoomOutIcon"
}

def process_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # 1. Replace imports from lucide-react to @radix-ui/react-icons
    import_regex = re.compile(r'import\s+\{([^}]+)\}\s+from\s+["\']lucide-react["\'];?')
    matches = import_regex.findall(content)
    
    if not matches and 'purple' not in content:
        return
        
    for match in matches:
        # extract individual icons, handling aliases like `Container as ContainerIcon`
        original_icons = [i.strip() for i in match.split(',')]
        new_icons = []
        for icon in original_icons:
            if not icon: continue
            if " as " in icon:
                real_name, alias = icon.split(" as ")
                real_name, alias = real_name.strip(), alias.strip()
                if alias in ICON_MAP:
                    mapped = ICON_MAP[alias]
                    new_icons.append(f"{mapped} as {alias}")
                    # But actually we need to replace the usage in code too, or just map it directly.
                    # It's better to just replace the alias with the actual radix icon in code.
                    # Let's map it and do text replace for the JSX tag.
            else:
                if icon in ICON_MAP:
                    new_icons.append(ICON_MAP[icon])
                    # Replace in JSX
                    content = re.sub(r'<' + icon + r'\b', '<' + ICON_MAP[icon], content)
                    content = re.sub(r'icon=\{' + icon + r'\}', f'icon={{{ICON_MAP[icon]}}}', content)
        
        # Replace the import statement
        replacement_import = "import { " + ", ".join(new_icons) + " } from \"@radix-ui/react-icons\";"
        content = re.sub(r'import\s+\{[^}]+\}\s+from\s+["\']lucide-react["\'];?', replacement_import, content, count=1)

    # 2. Handle aliases in code (like ContainerIcon -> BoxIcon)
    content = content.replace("<ContainerIcon", "<BoxIcon")
    content = content.replace("icon={ContainerIcon}", "icon={BoxIcon}")
    
    # Remove LucideIcon type usages
    content = re.sub(r'import\s+type\s+\{\s*LucideIcon\s*\}\s+from\s+["\']lucide-react["\'];?', '', content)
    content = content.replace("LucideIcon", "React.FC<any>")

    # 3. Replace "purple" with "amber"
    content = content.replace('"purple"', '"amber"')
    content = content.replace("'purple'", "'amber'")
    content = content.replace("tone=\"purple\"", "tone=\"amber\"")
    content = content.replace("color=\"purple\"", "color=\"amber\"")

    with open(filepath, 'w') as f:
        f.write(content)

# Walk directory
for root, _, files in os.walk('src/arbiter/ui'):
    for file in files:
        if file.endswith('.tsx') or file.endswith('.ts'):
            process_file(os.path.join(root, file))

print("Done refactoring icons and purple.")
