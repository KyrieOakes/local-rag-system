from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

# 定义上传文件的 保存目录 和 允许的 文件扩展名集合
UPLOAD_DIR = Path("data/raw")
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}

# 验证上传文件的扩展名是否在允许的范围内，如果不合法则抛出一个ValueError异常
def validate_file_extension(filename: str) -> None:
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix}")

# 构建一个安全的文件名，使用UUID生成一个唯一的文件名，并保留原文件的扩展名
def build_safe_filename(original_filename: str) -> str:
    suffix = Path(original_filename).suffix.lower()
    # 使用UUID生成一个唯一的文件名，并保留原文件的扩展名，
    # 确保上传的文件不会覆盖已有的文件，并且能够正确识别文件类型
    return f"{uuid4().hex}{suffix}"

# 异步保存上传的文件到指定目录，并返回保存后的文件路径
async def save_upload_file(file: UploadFile) -> str:
    validate_file_extension(file.filename)

    # 创建上传目录，如果目录不存在则创建，确保文件能够正确保存
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    safe_filename = build_safe_filename(file.filename)
    # 构建文件的完整路径，将安全的文件名与上传目录结合起来，确保文件能够正确保存到指定位置
    file_path = UPLOAD_DIR / safe_filename

    # 读取上传文件的内容，并将其写入到构建的文件路径中，完成文件的保存过程
    content = await file.read()
    file_path.write_bytes(content)

    # 返回保存后的文件路径，供后续处理使用，例如加载文档内容等
    return str(file_path)