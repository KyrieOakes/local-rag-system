"""
Qdrant 集合清理脚本。

删除指定的 Qdrant 集合（默认 local_rag_docs），清空所有已索引的文档向量。
用于开发/测试时重置向量数据库状态。

警告：此操作不可逆，所有已索引的文档分块将永久丢失。
"""

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse

QDRANT_URL = "http://127.0.0.1:6333"
COLLECTION_NAME = "local_rag_docs"

def main():
    client = QdrantClient(url=QDRANT_URL)

    try:
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]

        if COLLECTION_NAME not in collection_names:
            print(f"Collection not found: {COLLECTION_NAME}")
            print("Nothing to delete.")
            return

        client.delete_collection(collection_name=COLLECTION_NAME)
        print(f"Deleted collection: {COLLECTION_NAME}")

    except UnexpectedResponse as e:
        print("Qdrant returned an unexpected response:")
        print(e)

    except Exception as e:
        print("Failed to clear Qdrant collection:")
        print(e)

if __name__ == "__main__":
    main()

