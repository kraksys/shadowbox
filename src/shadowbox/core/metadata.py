import mimetypes
from pathlib import Path
from typing import Dict, Any
import zipfile
# Optional imports: The code works even if these are missing
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

class MetadataExtractor:
    """ Class to extract metadata from files based on their content type. """

    def extract(self, file_path: str) -> Dict[str, Any]:
        """ Analyze a file and return a dictionary of metadata.  """
        path = Path(file_path)
        if not path.exists():
            return {}

        meta = {}

        # 1. Basic MIME detection (Standard Library)
        mime_type, encoding = mimetypes.guess_type(path)
        meta["mime_type"] = mime_type or "application/octet-stream"
        meta["extension"] = path.suffix.lower()

        if not mime_type:
            return meta

        # 2. Image Extraction (Requires 'pip install Pillow')
        if mime_type.startswith("image/") and HAS_PIL:
            try:
                with Image.open(path) as img:
                    meta["width"] = img.width
                    meta["height"] = img.height
                    meta["format"] = img.format
                    meta["mode"] = img.mode
            except Exception as e:
                meta["extraction_error"] = f"Image error: {str(e)}"

        # 3. PDF Extraction (Requires 'pip install PyPDF2')
        elif mime_type == "application/pdf" and HAS_PDF:
            try:
                with open(path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    meta["page_count"] = len(reader.pages)
                    if reader.metadata:
                        info = {k.strip('/'): str(v) for k, v in reader.metadata.items()}
                        meta["pdf_info"] = info
            except Exception as e:
                meta["extraction_error"] = f"PDF error: {str(e)}"

        # 4. Text File Stats
        elif mime_type.startswith("text/"):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    line_count = 0
                    char_count = 0
                    for line in f:
                        line_count += 1
                        char_count += len(line)
                    meta["line_count"] = line_count
                    meta["char_count"] = char_count
            except Exception:
                pass
        
        # 5. ZIP Archive Info
        elif mime_type == "application/zip":
            try:
                with zipfile.ZipFile(path, 'r') as zf:
                    # Get info list
                    infolist = zf.infolist()
                    meta["file_count"] = len(infolist)
                    meta["uncompressed_size"] = sum(f.file_size for f in infolist)
                    # List first 5 files as preview
                    meta["file_list_preview"] = [f.filename for f in infolist[:5]]
            except Exception as e:
                 meta["extraction_error"] = f"Zip error: {str(e)}"

        return meta
    
