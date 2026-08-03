from langchain_openai import ChatOpenAI

def get_llm():
    return ChatOpenAI(
        base_url="http://localhost:1234/v1",  
        api_key="lm-studio",
        model="meta-llama-3.1-8b-instruct",                   
        temperature=0
    )