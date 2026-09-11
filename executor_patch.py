import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('app/services/executor.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '        result["image_url"] = image_url\n        errors: list[str] = []\n        ok_count = 0'
new = '''        result["image_url"] = image_url

        # Excel 数据文件
        if rule.send_excel and rows:
            try:
                import pandas as pd
                from ..config import IMAGE_DIR
                from datetime import datetime
                excel_name = "excel_{}_{}.xlsx".format(rule.id, datetime.now().strftime("%Y%m%d_%H%M%S"))
                excel_path = IMAGE_DIR / excel_name
                df = pd.DataFrame(rows, columns=columns)
                df.to_excel(excel_path, index=False, engine="openpyxl")
                base = image_store.base_url(db)
                if base:
                    excel_url = image_store.url_for(base, excel_name)
                    body += "\n\n📎 **\\u6570\\u636e\\u6587\\u4ef6**: [\\u70b9\\u51fb\\u4e0b\\u8f7d]({})".format(excel_url)
                    result["warnings"].append("\\u5df2\\u751f\\u6210 Excel \\u6570\\u636e\\u6587\\u4ef6")
            except Exception as exc:
                result["warnings"].append("\\u751f\\u6210 Excel \\u6587\\u4ef6\\u5931\\u8d25\\uff1a{}".format(exc))

        errors: list[str] = []
        ok_count = 0'''

content = content.replace(old, new)

with open('app/services/executor.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('executor.py Excel logic added')
