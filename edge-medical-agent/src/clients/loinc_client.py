"""
LOINC lookup client using Redis as the backing store.
"""
import logging
from typing import Optional, List
import redis.asyncio as redis

from ..models.loinc import LOINCCode, LOINCLookupResult
from ..config import settings

logger = logging.getLogger(__name__)


class LOINCClient:
    """
    Client for LOINC code lookups from Redis.
    Supports exact match, normalized name lookup, and synonym resolution.
    """
    
    def __init__(self, redis_client: redis.Redis, tenant_id: str):
        self._redis = redis_client
        self._tenant_id = tenant_id
    
    def _code_key(self, loinc_num: str) -> str:
        """Key for direct LOINC code lookup."""
        return f"loinc:{self._tenant_id}:code:{loinc_num}"
    
    def _name_key(self, normalized_name: str) -> str:
        """Key for name-to-code index."""
        return f"loinc:{self._tenant_id}:name:{normalized_name}"
    
    def _synonym_key(self, synonym: str) -> str:
        """Key for synonym-to-canonical mapping."""
        return f"loinc:{self._tenant_id}:synonym:{synonym}"
    
    def _class_key(self, loinc_class: str) -> str:
        """Key for class-to-codes index."""
        return f"loinc:{self._tenant_id}:class:{loinc_class}"
    
    @staticmethod
    def normalize_name(name: str) -> str:
        """Normalize test name for lookup."""
        return name.lower().strip().replace(" ", "_").replace("-", "_")
    
    async def lookup_by_code(self, loinc_num: str) -> LOINCLookupResult:
        """
        Look up LOINC entry by code number.
        
        Args:
            loinc_num: LOINC code (e.g., "2345-7")
        """
        key = self._code_key(loinc_num)
        data = await self._redis.hgetall(key)
        
        if data:
            return LOINCLookupResult(
                code=LOINCCode.from_redis_hash(data),
                found=True,
                match_type="exact",
                query=loinc_num,
                confidence=1.0
            )
        
        return LOINCLookupResult(
            found=False,
            match_type="none",
            query=loinc_num,
            confidence=0.0
        )

    async def lookup_by_name(self, test_name: str) -> LOINCLookupResult:
        """
        Look up LOINC entry by test name.
        Tries: exact normalized match -> synonym -> fuzzy (if enabled)
        
        Args:
            test_name: Test name (e.g., "Glucose", "GLU", "blood sugar")
        """
        normalized = self.normalize_name(test_name)
        
        # Try direct name lookup
        name_key = self._name_key(normalized)
        loinc_num = await self._redis.get(name_key)
        
        if loinc_num:
            result = await self.lookup_by_code(loinc_num)
            if result.found:
                result.match_type = "normalized"
                result.query = test_name
                result.confidence = 0.95
                return result
        
        # Try synonym lookup
        synonym_key = self._synonym_key(normalized)
        canonical = await self._redis.get(synonym_key)
        
        if canonical:
            # Look up the canonical name
            canonical_key = self._name_key(self.normalize_name(canonical))
            loinc_num = await self._redis.get(canonical_key)
            
            if loinc_num:
                result = await self.lookup_by_code(loinc_num)
                if result.found:
                    result.match_type = "synonym"
                    result.query = test_name
                    result.confidence = 0.85
                    return result
        
        # Fuzzy matching (if enabled)
        if settings.loinc_enable_fuzzy:
            fuzzy_result = await self._fuzzy_lookup(test_name)
            if fuzzy_result.found:
                return fuzzy_result
        
        return LOINCLookupResult(
            found=False,
            match_type="none",
            query=test_name,
            confidence=0.0
        )
    
    async def _fuzzy_lookup(self, test_name: str) -> LOINCLookupResult:
        """
        Perform fuzzy matching against LOINC names.
        Uses Redis SCAN to find potential matches.
        """
        try:
            from rapidfuzz import fuzz
        except ImportError:
            logger.warning("rapidfuzz not installed, fuzzy matching disabled")
            return LOINCLookupResult(found=False, match_type="none", query=test_name)
        
        normalized = self.normalize_name(test_name)
        best_match = None
        best_score = 0
        
        # Scan name index keys
        pattern = f"loinc:{self._tenant_id}:name:*"
        async for key in self._redis.scan_iter(match=pattern, count=100):
            # Extract name from key
            name_part = key.split(":")[-1]
            score = fuzz.ratio(normalized, name_part)
            
            if score > best_score and score >= settings.loinc_fuzzy_threshold:
                best_score = score
                best_match = key
        
        if best_match:
            loinc_num = await self._redis.get(best_match)
            if loinc_num:
                result = await self.lookup_by_code(loinc_num)
                if result.found:
                    result.match_type = "fuzzy"
                    result.query = test_name
                    result.confidence = best_score / 100.0
                    return result
        
        return LOINCLookupResult(found=False, match_type="none", query=test_name)

    async def get_codes_by_class(self, loinc_class: str) -> List[LOINCCode]:
        """
        Get all LOINC codes in a specific class.
        
        Args:
            loinc_class: Class name (e.g., "CHEM", "HEM/BC", "UA")
        """
        class_key = self._class_key(loinc_class)
        loinc_nums = await self._redis.smembers(class_key)
        
        codes = []
        for loinc_num in loinc_nums:
            result = await self.lookup_by_code(loinc_num)
            if result.found:
                codes.append(result.code)
        
        return codes
    
    async def search(
        self,
        query: str,
        limit: int = 10
    ) -> List[LOINCLookupResult]:
        """
        Search for LOINC codes matching a query.
        Returns multiple potential matches.
        """
        results = []
        
        # First try exact/normalized lookup
        exact = await self.lookup_by_name(query)
        if exact.found:
            results.append(exact)
        
        # If fuzzy enabled, get additional matches
        if settings.loinc_enable_fuzzy:
            try:
                from rapidfuzz import fuzz
                
                normalized = self.normalize_name(query)
                pattern = f"loinc:{self._tenant_id}:name:*"
                matches = []
                
                async for key in self._redis.scan_iter(match=pattern, count=500):
                    name_part = key.split(":")[-1]
                    score = fuzz.ratio(normalized, name_part)
                    if score >= 50:  # Lower threshold for search
                        matches.append((key, score))
                
                # Sort by score and take top matches
                matches.sort(key=lambda x: x[1], reverse=True)
                
                for key, score in matches[:limit]:
                    loinc_num = await self._redis.get(key)
                    if loinc_num:
                        result = await self.lookup_by_code(loinc_num)
                        if result.found and result.code.loinc_num not in [r.code.loinc_num for r in results if r.code]:
                            result.match_type = "fuzzy"
                            result.query = query
                            result.confidence = score / 100.0
                            results.append(result)
                            
            except ImportError:
                pass
        
        return results[:limit]
    
    async def get_metadata(self) -> dict:
        """Get LOINC data metadata for this tenant."""
        meta_key = f"loinc:{self._tenant_id}:metadata"
        return await self._redis.hgetall(meta_key) or {}
