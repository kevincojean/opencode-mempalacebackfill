import sqlite3
import json
from datetime import datetime
from typing import final
import inject
from pymonad.either import Either, Left, Right
from pymonad.maybe import Just

from mempalace_backfill.alias import Error
from mempalace_backfill.config_load_service import ConfigLoadService
from mempalace_backfill.db.models import Message

@final
class MessageQueryRepository:
    @inject.autoparams()
    def __init__(self, config_service: ConfigLoadService):
        self._config_service = config_service

    def get_messages(self, session_id: str, include_system: bool = False, db_path: str = None) -> Either[Error, list[Message]]:
        try:
            if not db_path:
                config = self._config_service.load_config()
                db_path = config["backfill"]["opencode"]["database_path"]
            
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            
            msg_query = """
                SELECT id, session_id, json_extract(data, '$.role') as role, time_created, data
                FROM message
                WHERE session_id = ?
            """
            cursor.execute(msg_query, [session_id])
            msg_rows = cursor.fetchall()
            
            if not msg_rows:
                conn.close()
                return Right([])

            message_ids = [row[0] for row in msg_rows]
            
            placeholders = ','.join(['?'] * len(message_ids))
            part_query = f"""
                SELECT message_id, json_extract(data, '$.text') as text
                FROM part
                WHERE message_id IN ({placeholders}) AND json_extract(data, '$.type') = 'text'
            """
            cursor.execute(part_query, message_ids)
            part_rows = cursor.fetchall()
            
            parts_map = {}
            for msg_id, text in part_rows:
                if text:
                    if msg_id not in parts_map:
                        parts_map[msg_id] = []
                    parts_map[msg_id].append(text)

            messages = []
            for m_id, s_id, role, time_ms, m_data in msg_rows:
                if not include_system and role == 'system':
                    continue
                
                content = ""
                if m_id in parts_map:
                    content = "\n".join(parts_map[m_id])
                
                if not content:
                    try:
                        data_json = json.loads(m_data)
                        content = data_json.get('summary', {}).get('body', "")
                    except:
                        pass
                
                messages.append(
                    Message(
                        session_id=s_id,
                        role=role or "unknown",
                        content=content,
                        timestamp=datetime.fromtimestamp(time_ms / 1000.0)
                    )
                )
            
            messages.sort(key=lambda x: x.timestamp)
            
            conn.close()
            return Right(messages)
        except Exception as e:
            return Left(Error(f"Failed to fetch messages: {str(e)}", Just(e)))
