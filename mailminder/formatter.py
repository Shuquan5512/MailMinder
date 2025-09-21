import markdown as md


def markdown_to_html(markdown_text: str) -> str:
    return md.markdown(markdown_text, extensions=["extra", "sane_lists"])


def wrap_html_body(content_html: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
body {{
  font-family: Arial, sans-serif;
  line-height: 1.6;
  padding: 1em;
  background:#f9f9f9;
  color:#333;
}}
h1,h2 {{
  color:#2c3e50;
}}
</style>
</head>
<body>
{content_html}
</body>
</html>"""
