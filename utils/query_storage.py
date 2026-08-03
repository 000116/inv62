import os
from datetime import datetime

class QueryStorage:
    def __init__(self, output_dir="output"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def merge_sections(self, translated_sections: list) -> str:

        merged_sql = "\n\n".join(
            section.strip().rstrip(";") + ";"
            for section in translated_sections
            if section.strip()
        )
        return merged_sql

    def save(self, query_name: str, merged_sql: str) -> str:

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = query_name.replace(" ", "_").lower()
        filename = f"{safe_name}_{timestamp}.sql"

        file_path = os.path.join(self.output_dir, filename)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(merged_sql)

        return file_path
