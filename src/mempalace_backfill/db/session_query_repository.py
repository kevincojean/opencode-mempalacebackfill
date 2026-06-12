import logging
import sqlite3
from datetime import datetime
from typing import final
import inject
from pymonad.either import Either, Left, Right
from pymonad.maybe import Just

from mempalace_backfill.alias import Error
from mempalace_backfill.config_load_service import ConfigLoadService
from mempalace_backfill.db.models import Session
from mempalace_backfill.db.filters import SessionFilters

@final
class SessionQueryRepository:
    @inject.autoparams()
    def __init__(self, config_service: ConfigLoadService):
        self._config_service = config_service

    def get_sessions(self, filters: SessionFilters) -> Either[Error, list[Session]]:
        try:
            db_path = filters.get("db_path")
            if not db_path:
                config = self._config_service.load_config()
                db_path = config["backfill"]["opencode"]["database_path"]
            
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            
            query = """
                SELECT id, title, time_created,
                (SELECT COUNT(*) FROM message WHERE session_id = session.id) as message_count
                FROM session
            """
            params = []
            where_clauses = []
            
            if filters.get("since"):
                where_clauses.append("time_created >= ?")
                params.append(int(filters["since"].timestamp() * 1000))
            
            if filters.get("until"):
                where_clauses.append("time_created <= ?")
                params.append(int(filters["until"].timestamp() * 1000))
                
            if filters.get("exclude_title"):
                where_clauses.append("title NOT LIKE ?")
                params.append(f"%{filters['exclude_title']}%")
                
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
            
            if filters.get("min_messages"):
                query += " GROUP BY session.id HAVING message_count >= ?"
                params.append(filters["min_messages"])
            
            query += " ORDER BY time_created DESC"
            
            limit = filters.get("max_sessions") or filters.get("limit", 1000)
            offset = filters.get("offset", 0)
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            logging.debug("Session query: LIMIT=%s, OFFSET=%s, filters=%s", limit, offset, dict(filters))
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            sessions = [
                Session(
                    id=row[0],
                    subject=row[1],
                    created_at=datetime.fromtimestamp(row[2] / 1000.0),
                    message_count=row[3]
                ) for row in rows
            ]
            
            conn.close()
            return Right(sessions)
        except Exception as e:
            return Left(Error(f"Failed to fetch sessions: {str(e)}", Just(e)))
