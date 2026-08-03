from langchain_openai import ChatOpenAI

def get_llm():
    return ChatOpenAI(
        base_url="http://localhost:1234/v1",  
        api_key="lm-studio",                  
        model="sqlcoder-7b-2",                    
        temperature=0
    )