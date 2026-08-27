import re
with open('src/arbiter/ui/app/globals.css', 'r') as f:
    css = f.read()

# Rip out all gradients
css = re.sub(r'background:\s*radial-gradient[^;]+;', 'background: var(--panel);', css)
css = re.sub(r'background:\s*linear-gradient[^;]+;', 'background: var(--panel);', css)
# Rip out backdrop filters
css = re.sub(r'backdrop-filter:\s*blur[^;]+;', '', css)
# Rip out box-shadows (mostly)
css = re.sub(r'box-shadow:\s*0\s+\d+px[^;]+;', 'box-shadow: none;', css)

with open('src/arbiter/ui/app/globals.css', 'w') as f:
    f.write(css)
