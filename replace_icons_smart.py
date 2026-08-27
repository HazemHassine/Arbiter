import os
import re

ICON_MAP = {
    "Activity": "ActivityLogIcon",
    "Archive": "ArchiveIcon",
    "ArrowRight": "ArrowRightIcon",
    "Bot": "AvatarIcon",
    "Box": "CubeIcon",
    "Brain": "LightningBoltIcon",
    "BrainCircuit": "LightningBoltIcon",
    "Check": "CheckIcon",
    "CheckCircle2": "CheckCircledIcon",
    "ChevronLeft": "ChevronLeftIcon",
    "Circle": "ValueIcon",
    "CircleHelp": "QuestionMarkCircledIcon",
    "Clock3": "ClockIcon",
    "Command": "RowsIcon",
    "Container": "BoxIcon",
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
    "Home": "Component1Icon",
    "ListTree": "ListBulletIcon",
    "LoaderCircle": "UpdateIcon",
    "Maximize2": "SizeIcon",
    "Menu": "HamburgerMenuIcon",
    "Network": "Share2Icon",
    "PanelLeftClose": "ViewVerticalIcon",
    "PanelLeftOpen": "ViewVerticalIcon",
    "Pause": "PauseIcon",
    "Play": "PlayIcon",
    "Radio": "RadiobuttonIcon",
    "RefreshCw": "ReloadIcon",
    "RotateCcw": "ResetIcon",
    "Route": "MagnifyingGlassIcon",
    "Save": "CheckIcon",
    "ScanSearch": "MagnifyingGlassIcon",
    "Search": "MagnifyingGlassIcon",
    "Send": "PaperPlaneIcon",
    "Server": "CubeIcon",
    "Settings": "GearIcon",
    "Settings2": "GearIcon",
    "ShieldAlert": "ExclamationTriangleIcon",
    "ShieldCheck": "LockClosedIcon",
    "Sparkles": "StarIcon",
    "Square": "SquareIcon",
    "Terminal": "CodeIcon",
    "Trash2": "TrashIcon",
    "User": "PersonIcon",
    "WandSparkles": "MagicWandIcon",
    "Wrench": "MixerHorizontalIcon",
    "X": "Cross2Icon",
    "XCircle": "CrossCircledIcon",
    "ZoomIn": "ZoomInIcon",
    "ZoomOut": "ZoomOutIcon"
}

def process_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # 1. Replace type imports
    content = re.sub(r'import\s+type\s+\{\s*LucideIcon\s*\}\s+from\s+["\']lucide-react["\'];?', 'import * as React from "react";', content)
    content = content.replace("LucideIcon", "React.FC<any>")

    # 2. Replace component imports
    import_regex = re.compile(r'import\s+\{([^}]+)\}\s+from\s+["\']lucide-react["\'];?', re.MULTILINE | re.DOTALL)
    def replacer(match):
        inner = match.group(1)
        original_icons = [i.strip() for i in inner.split(',')]
        new_icons = []
        for icon in original_icons:
            if not icon: continue
            if " as " in icon:
                real_name, alias = icon.split(" as ")
                real_name, alias = real_name.strip(), alias.strip()
                mapped = ICON_MAP.get(real_name, "CubeIcon") # fallback
                new_icons.append(f"{mapped} as {alias}")
            else:
                mapped = ICON_MAP.get(icon, "CubeIcon") # fallback
                new_icons.append(f"{mapped} as {icon}")
        return "import { " + ", ".join(new_icons) + " } from \"@radix-ui/react-icons\";"

    content = import_regex.sub(replacer, content)

    # 3. Replace "purple" with "amber"
    content = content.replace('"purple"', '"amber"')
    content = content.replace("'purple'", "'amber'")
    content = content.replace("tone=\"purple\"", "tone=\"amber\"")
    content = content.replace("color=\"purple\"", "color=\"amber\"")

    with open(filepath, 'w') as f:
        f.write(content)

for root, _, files in os.walk('src/arbiter/ui'):
    for file in files:
        if file.endswith('.tsx') or file.endswith('.ts'):
            process_file(os.path.join(root, file))

print("Done refactoring icons with alias technique.")
