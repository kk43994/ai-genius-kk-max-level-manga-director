"""One entry composer shared by source previews and the release builder."""
import json
import re


def entry_html(source, config, build=None, *, add_base=False):
    source = re.sub(r'<script type="module" src="(?:shell/bootstrap\.js|asset-lab\.js)"></script>', '', source)
    if 'src="_app/bootstrap.mjs"' not in source:
        source = source.replace('</body>', '<script type="module" src="_app/bootstrap.mjs"></script>\n</body>', 1)
    config_tag = '<script type="application/json" id="asset-lab-config">' + json.dumps(config, ensure_ascii=False).replace('<','\\u003c') + '</script>'
    source = re.sub(r'<script type="application/json" id="asset-lab-config">.*?</script>', '', source, flags=re.S)
    tags = config_tag
    for style in ('accounts/accounts.css', '_app/integration.css'):
        if f'href="{style}"' not in source:
            tags += f'<link rel="stylesheet" href="{style}">'
    if build and 'id="asset-lab-build"' not in source:
        tags += '<script type="application/json" id="asset-lab-build">' + json.dumps(build).replace('<','\\u003c') + '</script>'
    if add_base and not re.search(r'<base[\s>]', source, re.I):
        tags += '<base href="' + config['publicBasePath'] + '">'
    return source.replace('</head>', tags + '</head>', 1)
