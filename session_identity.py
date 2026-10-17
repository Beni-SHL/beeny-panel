"""Label only what a browser user agent actually discloses; never invent phone models."""
import re

def describe(agent):
    agent=str(agent or '')[:250]
    if 'iPad' in agent:device='iPad'
    elif 'iPhone' in agent:device='iPhone'
    elif 'Android' in agent:
        match=re.search(r'Android[^;)]*;\s*(?:[a-z]{2}[-_][A-Z]{2};\s*)?([^;)]+)',agent)
        model=match[1].split(' Build/')[0].strip() if match else ''
        device='Android'+(' · '+model if model and model not in {'K','Mobile'} else '')
    elif 'Windows' in agent:device='Windows PC'
    elif 'Macintosh' in agent:device='Mac'
    elif 'Linux' in agent:device='Linux'
    else:device='Device not reported'
    browser='Edge' if 'Edg/' in agent else 'Firefox' if 'Firefox/' in agent else 'Chrome' if 'Chrome/' in agent else 'Safari' if 'Safari/' in agent else ''
    return device+(' · '+browser if browser else '')
