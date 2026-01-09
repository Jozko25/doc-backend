
import asyncio
import time
import os
from docparser.config import get_settings
from docparser.normalizers.llm_extractor import LLMExtractor

async def main():
    settings = get_settings()
    extractor = LLMExtractor()
    
    # Simulate a realistic 1-page invoice (approx 2KB)
    dummy_content = "Item Description 12345 10.00\n" * 50
    
    print(f"DEBUG: Testing with payload size: {len(dummy_content)} chars")
    
    start = time.time()
    try:
        response = await extractor.client.chat.completions.create(
            model=extractor.model,
            messages=[
                {"role": "system", "content": "You are a parser. Return JSON."},
                {"role": "user", "content": f"Extract this: {dummy_content} into json keys 'items'"}
            ],
            response_format={"type": "json_object"}
        )
        duration = time.time() - start
        print(f"DEBUG: Realistic request finished in {duration:.2f}s")
    except Exception as e:
        print(f"DEBUG: Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
