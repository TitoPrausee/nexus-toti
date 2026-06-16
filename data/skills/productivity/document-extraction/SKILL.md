---
name: document-extraction
description: Extract text content from .docx, .xlsx, and .pdf files when specialized Python libraries aren't available. Uses zipfile + xml.etree for office formats. Works in constrained environments (Docker containers, minimal installs).
tags: [documents, docx, xlsx, pdf, extraction, offline]
---

# Document Extraction (No External Libraries)

Extract content from office documents using only Python stdlib (`zipfile`, `xml.etree.ElementTree`). Use when `python-docx`, `openpyxl`, `markitdown`, or `pdftotext` are not installed and can't be installed (e.g., no pip in container).

## .docx Extraction

```python
import zipfile
import xml.etree.ElementTree as ET

def extract_docx(path):
    """Extract all text and tables from a .docx file."""
    with zipfile.ZipFile(path) as z:
        with z.open('word/document.xml') as f:
            tree = ET.parse(f)
            root = tree.getroot()
        
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        
        paragraphs = []
        for p in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
            # Check for heading style
            pPr = p.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pPr')
            style = ''
            if pPr is not None:
                pStyle = pPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pStyle')
                if pStyle is not None:
                    style = pStyle.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '')
            
            texts = [t.text for t in p.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t') if t.text]
            line = ''.join(texts).strip()
            if line:
                prefix = '## ' if 'Heading' in style else ''
                paragraphs.append(f"{prefix}{line}")
        
        tables = []
        for tbl in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl'):
            for row in tbl.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr'):
                cells = []
                for tc in row.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc'):
                    cell_texts = [t.text for t in tc.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t') if t.text]
                    cells.append(''.join(cell_texts).strip())
                tables.append(' | '.join(cells))
        
        return '\n'.join(paragraphs), tables
```

## .xlsx Extraction

```python
import zipfile
import xml.etree.ElementTree as ET

def extract_xlsx(path):
    """Extract all cell data from first sheet of .xlsx file. Returns list of rows."""
    with zipfile.ZipFile(path) as z:
        # Read shared strings first
        shared_strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            with z.open('xl/sharedStrings.xml') as f:
                tree = ET.parse(f)
                root = tree.getroot()
                ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                for si in root.findall('.//ns:si', ns):
                    parts = [t.text for t in si.findall('.//ns:t', ns) if t.text]
                    shared_strings.append(''.join(parts))
        
        # Read sheet1
        rows = []
        with z.open('xl/worksheets/sheet1.xml') as f:
            tree = ET.parse(f)
            root = tree.getroot()
            ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            
            for row_elem in root.findall('.//ns:row', ns):
                row_data = {}
                for c in row_elem.findall('ns:c', ns):
                    ref = c.get('r', '')
                    t_attr = c.get('t', '')
                    v = c.find('ns:v', ns)
                    if v is not None and v.text:
                        if t_attr == 's':
                            idx = int(v.text)
                            row_data[ref] = shared_strings[idx] if idx < len(shared_strings) else '?'
                        else:
                            row_data[ref] = v.text
                    else:
                        row_data[ref] = ''
                rows.append(row_data)
        
        return rows, shared_strings
```

## .pdf Extraction

PDFs cannot be extracted without installed tools. Options in order of preference:
1. `pdftotext` (poppler-utils) - best text extraction
2. `python3 -m markitdown[path]` - if pip available
3. Vision AI - convert PDF to images first: `python scripts/office/soffice.py --headless --convert-to pdf file.pdf && pdftoppm -jpeg file.pdf slide`
4. Ask user to provide text content separately

## Mac ZIP Extraction

Always exclude `__MACOSX/` directory — it contains macOS metadata files (resource forks):
```bash
python3 -c "
import zipfile
with zipfile.ZipFile('file.zip') as z:
    z.extractall('/tmp/output/')
"
# Then clean up:
rm -rf /tmp/output/__MACOSX/
```

## Modifying .xlsx Files (Adding Columns/Data)

When `openpyxl` is not available, modify xlsx by manipulating the XML directly:

```python
import zipfile, xml.etree.ElementTree as ET, shutil, tempfile, os

XNS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'

def modify_xlsx(src_path, dst_path, new_column_cells, col_letter='N'):
    """Add cells to existing xlsx. new_column_cells = {row_num: text, ...}"""
    tmp_dir = tempfile.mkdtemp()
    with zipfile.ZipFile(src_path, 'r') as z:
        z.extractall(tmp_dir)
    
    # 1. Parse sharedStrings.xml — build index, add new strings
    ss_path = os.path.join(tmp_dir, 'xl', 'sharedStrings.xml')
    ss_tree = ET.parse(ss_path)
    ss_root = ss_tree.getroot()
    
    string_to_index = {}
    for si in ss_root.findall(f'{{{XNS}}}si'):
        parts = [t.text for t in si.findall(f'{{{XNS}}}t') if t.text]
        text = ''.join(parts)
        string_to_index[text] = len(string_to_index)
    
    def add_shared_string(text):
        if text in string_to_index:
            return string_to_index[text]
        idx = len(string_to_index)
        si = ET.SubElement(ss_root, f'{{{XNS}}}si')
        t = ET.SubElement(si, f'{{{XNS}}}t')
        t.text = text
        t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        string_to_index[text] = idx
        return idx
    
    # 2. Parse sheet1.xml — add cells to rows
    sheet_path = os.path.join(tmp_dir, 'xl', 'worksheets', 'sheet1.xml')
    sheet_tree = ET.parse(sheet_path)
    sheet_data = sheet_tree.getroot().find(f'{{{XNS}}}sheetData')
    
    for row_elem in sheet_data.findall(f'{{{XNS}}}row'):
        row_num = int(row_elem.get('r', '0'))
        if row_num in new_column_cells:
            str_idx = add_shared_string(new_column_cells[row_num])
            new_cell = ET.SubElement(row_elem, f'{{{XNS}}}c')
            new_cell.set('r', f'{col_letter}{row_num}')
            new_cell.set('t', 's')
            v = ET.SubElement(new_cell, f'{{{XNS}}}v')
            v.text = str(str_idx)
    
    # 3. Update string count
    ss_root.set('uniqueCount', str(len(string_to_index)))
    
    # 4. Save XMLs
    ss_tree.write(ss_path, xml_declaration=True, encoding='UTF-8')
    sheet_tree.write(sheet_path, xml_declaration=True, encoding='UTF-8')
    
    # 5. Rebuild xlsx from tmp_dir
    with zipfile.ZipFile(dst_path, 'w', zipfile.ZIP_DEFLATED) as zout:
        for root_dir, dirs, files in os.walk(tmp_dir):
            for file in files:
                file_path = os.path.join(root_dir, file)
                arcname = os.path.relpath(file_path, tmp_dir)
                zout.write(file_path, arcname)
    shutil.rmtree(tmp_dir)
```

Key points:
- Always add new text to `sharedStrings.xml` first, then reference by index in cells with `t="s"`
- Set `xml:space="preserve"` on `<t>` elements to preserve whitespace/newlines
- Rebuild the zip file from scratch after modifying (no in-place editing)
- Use `f'{{{XNS}}}element'` pattern for namespace-qualified element names (Python `{{` = literal `{`, then insert XNS)
- Column auto-width is NOT set — add `<col>` elements in sheet1.xml if needed

## Pitfalls

- **Shared strings index**: XLSX cells with `t="s"` reference the shared strings array by index. Must parse `sharedStrings.xml` first.
- **Merged cells**: XLSX merged cells only contain data in the top-left cell. Other cells appear empty.
- **Namespaces**: All docx/xlsx XML uses `http://schemas.openxmlformats.org/wordprocessingml/2006/main` (docx) or `http://schemas.openxmlformats.org/spreadsheetml/2006/main` (xlsx). Must use these in ET lookups.
- **No styling**: This approach extracts text only. Bold, colors, fonts, and formatting are lost.
- **pip often missing**: In Docker containers, `python3 -m pip` may not work. Use the stdlib approach above.
- **NEVER modify xlsx via raw XML**: Trying to add columns/data by manipulating the XML directly (sharedStrings.xml + sheet1.xml) produces corrupt files that Excel flags as "unreadable content" and repairs by removing content. Tested and confirmed: adding a column N with shared strings via XML manipulation → Excel warns "repariert oder entfernt nicht lesbaren Inhalt" and strips the changes. The stdlib approach is read-only.
- **ALWAYS prefer Markdown over xlsx writes**: When users need modified/annotated spreadsheet data (e.g. adding analysis columns, unclear items, comments), output as .md table instead of patching the xlsx. Markdown tables are readable in git, Telegram, and editors. The original xlsx can stay unchanged in the repo as reference.
- **Column auto-width**: Adding cells via XML won't auto-size columns. Add `<col>` elements or use explicit widths if needed.
- **Namespace pattern**: `f'{{{XNS}}}c'` Python pattern: `{{` = literal `{`, then XNS is inserted, then `}` closes. This produces `{ns_uri}c` which is correct for ET qualified names.
- **Modified xlsx may be corrupt**: XML-level modifications (adding columns, cells) often produce files that Excel flags as "unreadable content" and offers to repair. This can silently lose data or formatting. **Prefer outputting results as Markdown instead of modifying xlsx files.** If xlsx modification is truly needed, test the output in Excel before delivering to the user.