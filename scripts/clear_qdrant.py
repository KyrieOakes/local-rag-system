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

