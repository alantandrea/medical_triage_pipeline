"""
LOINC data loader - loads LOINC CSV data into Redis.
"""
import csv
import json
import logging
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime, timezone
import redis.asyncio as redis

from ..models.loinc import LOINCCode, LOINCSynonymEntry
from ..config import settings

logger = logging.getLogger(__name__)


class LOINCLoader:
    """
    Loads LOINC reference data from CSV files into Redis.
    
    Supports:
    - Full load: Clears existing data and loads fresh
    - Incremental load: Adds/updates without clearing
    - Synonym loading: Loads custom synonym mappings
    """
    
    # Column mapping from LOINC CSV to our model
    CSV_COLUMNS = {
        "LOINC_NUM": "loinc_num",
        "LONG_COMMON_NAME": "long_common_name",
        "SHORTNAME": "short_name",
        "COMPONENT": "component",
        "PROPERTY": "property",
        "TIME_ASPCT": "time_aspect",
        "SYSTEM": "system",
        "SCALE_TYP": "scale_type",
        "METHOD_TYP": "method_type",
        "CLASS": "loinc_class",
        "CLASSTYPE": "class_type",
        "ORDER_OBS": "order_obs",
        "STATUS": "status",
    }
    
    def __init__(
        self,
        redis_client: redis.Redis,
        tenant_id: str,
        data_dir: Optional[str] = None
    ):
        self._redis = redis_client
        self._tenant_id = tenant_id
        self._data_dir = Path(data_dir or settings.loinc_data_dir)
    
    def _code_key(self, loinc_num: str) -> str:
        return f"loinc:{self._tenant_id}:code:{loinc_num}"
    
    def _name_key(self, normalized_name: str) -> str:
        return f"loinc:{self._tenant_id}:name:{normalized_name}"
    
    def _synonym_key(self, synonym: str) -> str:
        return f"loinc:{self._tenant_id}:synonym:{synonym}"
    
    def _class_key(self, loinc_class: str) -> str:
        return f"loinc:{self._tenant_id}:class:{loinc_class}"
    
    def _meta_key(self) -> str:
        return f"loinc:{self._tenant_id}:metadata"
    
    @staticmethod
    def normalize_name(name: str) -> str:
        return name.lower().strip().replace(" ", "_").replace("-", "_")

    async def load_full(
        self,
        csv_path: Optional[str] = None,
        clear_existing: bool = True
    ) -> Dict:
        """
        Perform full LOINC data load from CSV.
        
        Args:
            csv_path: Path to Loinc.csv file. Defaults to data_dir/Loinc.csv
            clear_existing: Whether to clear existing data first
        
        Returns:
            dict with load statistics
        """
        csv_file = Path(csv_path) if csv_path else self._data_dir / "Loinc.csv"
        
        if not csv_file.exists():
            raise FileNotFoundError(f"LOINC CSV not found: {csv_file}")
        
        start_time = datetime.now(timezone.utc)
        logger.info(f"Starting full LOINC load from {csv_file}")
        
        if clear_existing:
            await self._clear_tenant_data()
        
        loaded = 0
        skipped = 0
        errors = 0
        classes_seen = set()
        
        # Use pipeline for batch operations
        pipe = self._redis.pipeline()
        batch_size = 500
        
        with open(csv_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                try:
                    # Map CSV columns to model fields
                    model_data = {}
                    for csv_col, model_field in self.CSV_COLUMNS.items():
                        if csv_col in row:
                            model_data[model_field] = row[csv_col] or None
                    
                    # Skip if no LOINC number
                    if not model_data.get("loinc_num"):
                        skipped += 1
                        continue
                    
                    # Skip deprecated codes
                    if model_data.get("status") == "DEPRECATED":
                        skipped += 1
                        continue
                    
                    # Create and validate model
                    try:
                        code = LOINCCode(**model_data)
                    except Exception as e:
                        logger.debug(f"Validation error for {model_data.get('loinc_num')}: {e}")
                        skipped += 1
                        continue
                    
                    # Store code hash
                    code_key = self._code_key(code.loinc_num)
                    pipe.hset(code_key, mapping=code.to_redis_hash())
                    
                    # Index by normalized name
                    if code.long_common_name:
                        name_key = self._name_key(self.normalize_name(code.long_common_name))
                        pipe.set(name_key, code.loinc_num)
                    
                    # Index by class
                    if code.loinc_class:
                        class_key = self._class_key(code.loinc_class)
                        pipe.sadd(class_key, code.loinc_num)
                        classes_seen.add(code.loinc_class)
                    
                    loaded += 1
                    
                    # Execute batch
                    if loaded % batch_size == 0:
                        await pipe.execute()
                        pipe = self._redis.pipeline()
                        logger.info(f"Loaded {loaded} LOINC codes...")
                        
                except Exception as e:
                    errors += 1
                    logger.error(f"Error loading row: {e}")
        
        # Execute remaining
        await pipe.execute()
        
        # Store metadata
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()
        
        await self._redis.hset(self._meta_key(), mapping={
            "loaded_at": end_time.isoformat(),
            "source_file": str(csv_file),
            "total_codes": str(loaded),
            "classes": ",".join(sorted(classes_seen)),
            "load_duration": str(duration)
        })
        
        result = {
            "status": "completed",
            "loaded": loaded,
            "skipped": skipped,
            "errors": errors,
            "classes": len(classes_seen),
            "duration_seconds": duration
        }
        
        logger.info(f"LOINC load completed: {loaded} codes, {len(classes_seen)} classes, {duration:.1f}s")
        return result

    async def load_synonyms(
        self,
        synonyms_path: Optional[str] = None
    ) -> Dict:
        """
        Load custom synonym mappings from JSON file.
        
        Expected JSON format:
        {
            "synonyms": [
                {"synonym": "GLU", "canonical": "glucose", "source": "common_abbreviation"},
                {"synonym": "blood sugar", "canonical": "glucose", "source": "patient_friendly"}
            ]
        }
        """
        syn_file = Path(synonyms_path) if synonyms_path else Path(settings.loinc_synonyms_file)
        
        if not syn_file.exists():
            logger.warning(f"Synonyms file not found: {syn_file}")
            return {"status": "skipped", "reason": "file_not_found"}
        
        logger.info(f"Loading synonyms from {syn_file}")
        
        with open(syn_file, "r") as f:
            data = json.load(f)
        
        synonyms = data.get("synonyms", [])
        loaded = 0
        errors = 0
        
        pipe = self._redis.pipeline()
        
        for entry in synonyms:
            try:
                syn = LOINCSynonymEntry(**entry)
                syn_key = self._synonym_key(self.normalize_name(syn.synonym))
                pipe.set(syn_key, syn.canonical)
                loaded += 1
            except Exception as e:
                errors += 1
                logger.error(f"Error loading synonym {entry}: {e}")
        
        await pipe.execute()
        
        # Update metadata
        await self._redis.hset(self._meta_key(), mapping={
            "synonyms_loaded": str(loaded),
            "synonyms_file": str(syn_file)
        })
        
        logger.info(f"Loaded {loaded} synonyms")
        return {"status": "completed", "loaded": loaded, "errors": errors}
    
    async def _clear_tenant_data(self) -> int:
        """Clear all LOINC data for this tenant."""
        pattern = f"loinc:{self._tenant_id}:*"
        deleted = 0
        
        async for key in self._redis.scan_iter(match=pattern, count=1000):
            await self._redis.delete(key)
            deleted += 1
        
        logger.info(f"Cleared {deleted} existing LOINC keys")
        return deleted
    
    async def check_data(self) -> Dict:
        """Check current LOINC data status."""
        meta = await self._redis.hgetall(self._meta_key())
        
        # Count codes
        code_pattern = f"loinc:{self._tenant_id}:code:*"
        code_count = 0
        async for _ in self._redis.scan_iter(match=code_pattern, count=1000):
            code_count += 1
        
        return {
            "tenant_id": self._tenant_id,
            "code_count": code_count,
            "loaded_at": meta.get("loaded_at"),
            "source_file": meta.get("source_file"),
            "classes": meta.get("classes", "").split(",") if meta.get("classes") else [],
            "synonyms_loaded": int(meta.get("synonyms_loaded", 0))
        }
