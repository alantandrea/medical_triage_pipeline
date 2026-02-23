"""
LOINC ETL Job - Standalone script for loading LOINC data into Redis.

Usage:
    python -m src.loinc.etl_job --mode full --csv-path /path/to/Loinc.csv
    python -m src.loinc.etl_job --mode synonyms --synonyms-path /path/to/synonyms.json
    python -m src.loinc.etl_job --mode check
"""
import asyncio
import argparse
import logging
import sys
from pathlib import Path

import redis.asyncio as redis

from .loader import LOINCLoader
from .admin import LOINCAdmin
from ..config import settings

logger = logging.getLogger(__name__)


async def run_etl(args):
    """Execute ETL based on command line arguments."""
    
    # Connect to Redis
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    
    try:
        await redis_client.ping()
        logger.info(f"Connected to Redis at {settings.redis_url}")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        sys.exit(1)
    
    tenant_id = args.tenant_id or settings.tenant_id
    
    try:
        if args.mode == "full":
            # Full load from CSV
            loader = LOINCLoader(redis_client, tenant_id, args.data_dir)
            result = await loader.load_full(
                csv_path=args.csv_path,
                clear_existing=not args.no_clear
            )
            
            # Also load synonyms if available
            if args.synonyms_path or Path(settings.loinc_synonyms_file).exists():
                syn_result = await loader.load_synonyms(args.synonyms_path)
                result["synonyms"] = syn_result
            
            print_result("Full Load", result)
            
        elif args.mode == "incremental":
            # Incremental load (add without clearing)
            loader = LOINCLoader(redis_client, tenant_id, args.data_dir)
            result = await loader.load_full(
                csv_path=args.csv_path,
                clear_existing=False
            )
            print_result("Incremental Load", result)
            
        elif args.mode == "synonyms":
            # Load synonyms only
            loader = LOINCLoader(redis_client, tenant_id, args.data_dir)
            result = await loader.load_synonyms(args.synonyms_path)
            print_result("Synonyms Load", result)
            
        elif args.mode == "check":
            # Check current data status
            loader = LOINCLoader(redis_client, tenant_id, args.data_dir)
            result = await loader.check_data()
            print_result("Data Check", result)
            
        elif args.mode == "stats":
            # Get detailed statistics
            admin = LOINCAdmin(redis_client, tenant_id)
            result = await admin.get_statistics()
            print_result("Statistics", result)
            
        elif args.mode == "validate":
            # Validate data integrity
            admin = LOINCAdmin(redis_client, tenant_id)
            result = await admin.validate_data()
            print_result("Validation", result)
            
    finally:
        await redis_client.close()


def print_result(title: str, result: dict):
    """Pretty print result."""
    print(f"\n{'='*50}")
    print(f" {title}")
    print(f"{'='*50}")
    
    for key, value in result.items():
        if isinstance(value, list) and len(value) > 10:
            print(f"  {key}: [{len(value)} items]")
        else:
            print(f"  {key}: {value}")
    
    print()


def main():
    parser = argparse.ArgumentParser(
        description="LOINC ETL Job - Load LOINC reference data into Redis"
    )
    
    parser.add_argument(
        "--mode",
        choices=["full", "incremental", "synonyms", "check", "stats", "validate"],
        default="check",
        help="ETL mode (default: check)"
    )
    
    parser.add_argument(
        "--csv-path",
        help="Path to Loinc.csv file"
    )
    
    parser.add_argument(
        "--synonyms-path",
        help="Path to synonyms.json file"
    )
    
    parser.add_argument(
        "--data-dir",
        help="Directory containing LOINC data files"
    )
    
    parser.add_argument(
        "--tenant-id",
        help=f"Tenant ID (default: {settings.tenant_id})"
    )
    
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Don't clear existing data before full load"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Run ETL
    asyncio.run(run_etl(args))


if __name__ == "__main__":
    main()
