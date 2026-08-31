import os
import requests

def query_perplexity(prompt: str, model: str = "sonar-pro") -> dict:
    """Queries the Perplexity API for live grounded research and citations.
    
    Available models:
      - sonar: Fast, lightweight search (Llama 3.3 70B based)
      - sonar-pro: Deep web retrieval with enhanced sources
      - sonar-reasoning-pro: Multi-step reasoning + search
    """
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        raise ValueError("Error: PERPLEXITY_API_KEY environment variable is missing.")

    url = "https://api.perplexity.ai/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a research agent. Provide detailed, factual briefings with clear structure."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.2,
        "return_citations": True
    }

    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()

if __name__ == "__main__":
    user_prompt = input("Enter research topic: ")
    print("\n[+] Running Perplexity Search Pipeline...\n")
    
    try:
        result = query_perplexity(user_prompt)
        content = result["choices"][0]["message"]["content"]
        citations = result.get("citations", [])

        print("=== RESEARCH SUMMARY ===")
        print(content)
        
        if citations:
            print("\n=== VERIFIED CITATIONS ===")
            for i, url in enumerate(citations, 1):
                print(f"[{i}] {url}")
                
    except Exception as err:
        print(f"API Execution Error: {err}")