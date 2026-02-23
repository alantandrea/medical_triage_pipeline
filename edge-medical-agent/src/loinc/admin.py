"""
LOINC administration utilities.
"""
import logging
from typing import Optional, List
import redis.asyncio as redis

from ..models.loinc import LOINCCode, LOINCSynonymEntry
from ..config import settings

logger = logging.getLogger(__name__)


class LOINCAdmin:
    """
    Administrative operations for LOINC data.
    
    Provides:
    - Add/update individual codes
    - Add/remove synonyms
    - Data validation
    - Statistics and reporting
    """
    
    def __init__(self, redis_client: redis.Redis, tenant_id: str):
        self._redis = redis_client
        self._tenant_id = tenant_id
    
    def _code_key(self, loinc_num: str) -> str:
        return f"loinc:{self._tenant_id}:code:{loinc_num}"
    
    def _name_key(self, normalized_name: str) -> str:
        return f"loinc:{self._tenant_id}:name:{normalized_name}"
    
    def _synonym_key(self, synonym: str) -> str:
        return f"loinc:{self._tenant_id}:synonym:{synonym}"
    
    def _class_key(self, loinc_class: str) -> str:
        return f"loinc:{self._tenant_id}:class:{loinc_class}"
    
    @staticmethod
    def normalize_name(name: str) -> str:
        return name.lower().strip().replace(" ", "_").replace("-", "_")
    
    async def add_code(self, code: LOINCCode) -> bool:
        """Add or update a single LOINC code."""
        try:
            pipe = self._redis.pipeline()
            
            # Store code hash
            code_key = self._code_key(code.loinc_num)
            pipe.hset(code_key, mapping=code.to_redis_hash())
            
            # Index by name
            if code.long_common_name:
                name_key = self._name_key(self.normalize_name(code.long_common_name))
                pipe.set(name_key, code.loinc_num)
            
            # Index by class
            if code.loinc_class:
                class_key = self._class_key(code.loinc_class)
                pipe.sadd(class_key, code.loinc_num)
            
            await pipe.execute()
            logger.info(f"Added/updated LOINC code: {code.loinc_num}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add LOINC code {code.loinc_num}: {e}")
            return False
    
    async def remove_code(self, loinc_num: str) -> bool:
        """Remove a LOINC code and its indexes."""
        try:
            # Get existing code to find indexes to remove
            code_key = self._code_key(loinc_num)
            data = await self._redis.hgetall(code_key)
            
            if not data:
                return False
            
            pipe = self._redis.pipeline()
            
            # Remove code hash
            pipe.delete(code_key)
            
            # Remove name index
            if data.get("long_common_name"):
                name_key = self._name_key(self.normalize_name(data["long_common_name"]))
                pipe.delete(name_key)
            
            # Remove from class set
            if data.get("class"):
                class_key = self._class_key(data["class"])
                pipe.srem(class_key, loinc_num)
            
            await pipe.execute()
            logger.info(f"Removed LOINC code: {loinc_num}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove LOINC code {loinc_num}: {e}")
            return False

    async def add_synonym(self, synonym: str, canonical: str) -> bool:
        """Add a synonym mapping."""
        try:
            syn_key = self._synonym_key(self.normalize_name(synonym))
            await self._redis.set(syn_key, canonical)
            logger.info(f"Added synonym: {synonym} -> {canonical}")
            return True
        except Exception as e:
            logger.error(f"Failed to add synonym {synonym}: {e}")
            return False
    
    async def remove_synonym(self, synonym: str) -> bool:
        """Remove a synonym mapping."""
        try:
            syn_key = self._synonym_key(self.normalize_name(synonym))
            result = await self._redis.delete(syn_key)
            if result:
                logger.info(f"Removed synonym: {synonym}")
            return result > 0
        except Exception as e:
            logger.error(f"Failed to remove synonym {synonym}: {e}")
            return False
    
    async def list_synonyms(self) -> List[dict]:
        """List all synonym mappings."""
        pattern = f"loinc:{self._tenant_id}:synonym:*"
        synonyms = []
        
        async for key in self._redis.scan_iter(match=pattern, count=1000):
            synonym = key.split(":")[-1]
            canonical = await self._redis.get(key)
            synonyms.append({
                "synonym": synonym,
                "canonical": canonical
            })
        
        return synonyms
    
    async def get_statistics(self) -> dict:
        """Get LOINC data statistics."""
        # Count codes
        code_pattern = f"loinc:{self._tenant_id}:code:*"
        code_count = 0
        async for _ in self._redis.scan_iter(match=code_pattern, count=1000):
            code_count += 1
        
        # Count synonyms
        syn_pattern = f"loinc:{self._tenant_id}:synonym:*"
        syn_count = 0
        async for _ in self._redis.scan_iter(match=syn_pattern, count=1000):
            syn_count += 1
        
        # Count classes
        class_pattern = f"loinc:{self._tenant_id}:class:*"
        classes = []
        async for key in self._redis.scan_iter(match=class_pattern, count=100):
            class_name = key.split(":")[-1]
            count = await self._redis.scard(key)
            classes.append({"class": class_name, "count": count})
        
        # Get metadata
        meta_key = f"loinc:{self._tenant_id}:metadata"
        meta = await self._redis.hgetall(meta_key)
        
        return {
            "tenant_id": self._tenant_id,
            "total_codes": code_count,
            "total_synonyms": syn_count,
            "classes": sorted(classes, key=lambda x: x["count"], reverse=True),
            "loaded_at": meta.get("loaded_at"),
            "source_file": meta.get("source_file")
        }
    
    async def validate_data(self) -> dict:
        """Validate LOINC data integrity."""
        issues = []
        
        # Check for orphaned name indexes
        name_pattern = f"loinc:{self._tenant_id}:name:*"
        async for key in self._redis.scan_iter(match=name_pattern, count=1000):
            loinc_num = await self._redis.get(key)
            if loinc_num:
                code_key = self._code_key(loinc_num)
                exists = await self._redis.exists(code_key)
                if not exists:
                    issues.append({
                        "type": "orphaned_name_index",
                        "key": key,
                        "loinc_num": loinc_num
                    })
        
        return {
            "valid": len(issues) == 0,
            "issues": issues[:100]  # Limit to first 100
        }
