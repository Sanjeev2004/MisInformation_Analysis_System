import asyncio
import json
import operator
from typing import Annotated, Sequence, TypedDict, List, Dict, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from duckduckgo_search import DDGS

from langchain_groq import ChatGroq
from backend.config import GROQ_API_KEY
from backend.services.retriever import retrieve_fact_checks

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    claim: str
    loops: int
    final_result: Dict[str, Any]

# Using llama-3.3-70b-versatile for the agent
llm = ChatGroq(model="llama-3.3-70b-versatile", groq_api_key=GROQ_API_KEY, temperature=0.2)

def get_tools():
    return [
        {
            "name": "fact_check_search",
            "description": "Searches the Google Fact Check API and mock registry for the query. Always try this first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "web_search",
            "description": "Searches DuckDuckGo for general web results. Use this if fact checks are insufficient.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "submit_verdict",
            "description": "Submits the final verdict and explanation. Call this ONLY when you have enough evidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "verdict": {"type": "string", "enum": ["Likely True", "Suspicious", "Likely False", "Uncertain"]},
                    "overall_risk": {"type": "number", "description": "Risk score from 0 to 100"},
                    "confidence": {"type": "number", "description": "Confidence score from 0 to 100"},
                    "explanation": {"type": "string", "description": "Detailed explanation of why this verdict was reached"},
                    "highlights": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "phrase": {"type": "string"},
                                "category": {"type": "string"}
                            }
                        }
                    }
                },
                "required": ["verdict", "overall_risk", "confidence", "explanation", "highlights"]
            }
        }
    ]

llm_with_tools = llm.bind_tools(get_tools())

async def agent_node(state: AgentState):
    messages = state.get('messages', [])
    claim = state.get('claim', '')
    loops = state.get('loops', 0)
    
    if not messages:
        sys_msg = SystemMessage(content=(
            "You are an expert misinformation investigator. "
            "Your task is to verify the following claim by gathering evidence using your tools. "
            "1. Use `fact_check_search` to find existing fact-checks.\n"
            "2. If needed, use `web_search` to find broader context.\n"
            "3. Synthesize the evidence and use `submit_verdict` to return your final analysis.\n"
            "Do NOT use submit_verdict until you have searched for evidence."
        ))
        human_msg = HumanMessage(content=f"Investigate this claim context:\n{claim}")
        messages = [sys_msg, human_msg]
        
    response = await llm_with_tools.ainvoke(messages)
    return {"messages": [response], "loops": loops + 1}

async def tool_node(state: AgentState):
    messages = state['messages']
    last_message = messages[-1]
    
    tool_messages = []
    final_result = state.get("final_result", None)
    
    if isinstance(last_message, AIMessage) and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        # Mutate the AIMessage to only have the first tool call to prevent Gemini validation errors on parallel tools
        if len(last_message.tool_calls) > 1:
            last_message.tool_calls = [last_message.tool_calls[0]]
            
        tool_call = last_message.tool_calls[0]
        name = tool_call['name']
        args = tool_call['args']
        tool_call_id = tool_call['id']
        
        if name == "submit_verdict":
            final_result = args
            tool_messages.append(ToolMessage(content="Verdict submitted.", name=name, tool_call_id=tool_call_id))
        elif name == "fact_check_search":
            res = await retrieve_fact_checks(args.get('query', ''))
            tool_messages.append(ToolMessage(content=json.dumps(res), name=name, tool_call_id=tool_call_id))
        elif name == "web_search":
            def do_search():
                try:
                    return DDGS().text(args.get('query', ''), max_results=3)
                except Exception as e:
                    return [{"error": str(e)}]
            res = await asyncio.to_thread(do_search)
            tool_messages.append(ToolMessage(content=json.dumps(res), name=name, tool_call_id=tool_call_id))
            
    return {"messages": tool_messages, "final_result": final_result}

def should_continue(state: AgentState) -> str:
    messages = state['messages']
    last_message = messages[-1]
    
    if state.get("final_result"):
        return "end"
        
    if state.get("loops", 0) > 4:
        return "end"
        
    if isinstance(last_message, AIMessage) and not getattr(last_message, 'tool_calls', None):
        return "end"
        
    return "continue"

workflow = StateGraph(AgentState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)

workflow.set_entry_point("agent")
workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "continue": "tools",
        "end": END
    }
)
workflow.add_edge("tools", "agent")

compiled_agent = workflow.compile()

async def run_agentic_analysis(claim_text: str, source_url: str = None, domain_score: float = None):
    """Executes the LangGraph autonomous agent to analyze the claim."""
    context = claim_text
    if source_url:
        context += f"\nSource URL: {source_url}"
    if domain_score is not None:
        context += f"\nDomain Credibility Score (0.0 to 1.0, lower is riskier): {domain_score}"
        
    final_state = await compiled_agent.ainvoke({
        "claim": context,
        "messages": [],
        "loops": 0,
        "final_result": None
    })
    
    # Parse evidence from the tools used by the agent
    evidence_list = []
    for msg in final_state["messages"]:
        if getattr(msg, "type", "") == "tool" and msg.name in ["fact_check_search", "web_search"]:
            try:
                data = json.loads(msg.content)
                if isinstance(data, list):
                    for item in data:
                        if "error" in item: continue
                        evidence_list.append({
                            "title": item.get("title", "Search Result"),
                            "snippet": item.get("snippet", item.get("body", "No description available")),
                            "url": item.get("url", item.get("href", "")),
                            "source": item.get("source", "Web Search"),
                            "type": "fact-check" if msg.name == "fact_check_search" else "web-search",
                            "similarity_score": item.get("similarity_score", 0.7)
                        })
            except Exception:
                pass
                
    result = final_state.get("final_result")
    if not result:
        result = {
            "verdict": "Uncertain",
            "overall_risk": 50.0,
            "confidence": 0.0,
            "explanation": "The investigation agent failed to return a structured verdict.",
            "highlights": []
        }
        
    return result, evidence_list
