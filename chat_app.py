import streamlit as st
import asyncio
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración de página
st.set_page_config(
    page_title="Asesor de Competencia",
    page_icon="🛍️",
    layout="centered"
)

# Inicializar componentes
from chatbot.agent import ChatbotAgent

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Hello! Tell me what product you're looking for or which one you want to compare prices with competitors."}]
    
if "agent" not in st.session_state:
    # Se inicializa solo una vez por sesión
    st.session_state.agent = ChatbotAgent()

st.title("🛍️ Price & Competitor Advisor")
st.markdown("Ask me about any product to find out if competitors have it, compare prices, or find alternatives.")

# Sidebar
with st.sidebar:
    st.header("Session")
    
    # Mostrar usuario conectado si se usa Streamlit Cloud SSO
    if hasattr(st, "experimental_user") and hasattr(st.experimental_user, "email") and st.experimental_user.email:
        st.write(f"👤 Logged in as: **{st.experimental_user.email}**")
    else:
        st.write("👤 Local Mode")
        
    st.markdown("---")
    selected_model = st.selectbox("Brain (Model)", ["gpt-4o-mini", "gpt-4o"], index=1)
    
    if st.button("Clear History"):
        st.session_state.messages = [{"role": "assistant", "content": "Hello! Tell me what product you're looking for or which one you want to compare prices with competitors."}]
        st.rerun()

# Mostrar historial de mensajes
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if isinstance(message["content"], list):
            for item in message["content"]:
                if item["type"] == "text":
                    st.markdown(item["text"])
                elif item["type"] == "image_url":
                    # Extraer base64 y mostrar imagen
                    url = item["image_url"]["url"]
                    st.markdown(f'<img src="{url}" width="200" style="border-radius: 8px;">', unsafe_allow_html=True)
        else:
            st.markdown(message["content"])
            
        if "metadata" in message:
            meta = message["metadata"]
            u = meta["tokens"]
            st.caption(f"⚙️ **Model:** {meta['model']} | **Tokens:** {u['total_tokens']} (In: {u['prompt_tokens']} | Out: {u['completion_tokens']}) | **Cost:** ${meta['cost']:.6f} USD")

# Input del usuario
prompt_obj = st.chat_input("E.g. Royal Canin Mini Adult 8kg food...", accept_file=True, file_type=["png", "jpg", "jpeg"])
if prompt_obj:
    text_prompt = prompt_obj.text if prompt_obj.text else "Find products similar to this image"
    
    if prompt_obj.files:
        uploaded_img = prompt_obj.files[0]
        import base64
        bytes_data = uploaded_img.getvalue()
        base64_img = base64.b64encode(bytes_data).decode("utf-8")
        img_type = uploaded_img.type
        
        user_content = [
            {"type": "text", "text": text_prompt},
            {"type": "image_url", "image_url": {"url": f"data:{img_type};base64,{base64_img}"}}
        ]
        
        st.session_state.messages.append({"role": "user", "content": user_content})
        with st.chat_message("user"):
            st.markdown(text_prompt)
            st.markdown(f'<img src="data:{img_type};base64,{base64_img}" width="200" style="border-radius: 8px;">', unsafe_allow_html=True)
    else:
        st.session_state.messages.append({"role": "user", "content": text_prompt})
        with st.chat_message("user"):
            st.markdown(text_prompt)
        
    # Llamar al agente
    with st.chat_message("assistant"):
        with st.spinner("Searching database and analyzing competitors..."):
            try:
                historial_a_enviar = [m for m in st.session_state.messages if m["role"] in ["user", "assistant"]]
                
                # Usar el modo stream=True del agente
                stream_generator = st.session_state.agent.process_chat(historial_a_enviar, stream=True, model=selected_model)
                
                # st.write_stream consume el generador de OpenAI o nuestro generador custom
                respuesta = st.write_stream(stream_generator)
                
                msg_data = {"role": "assistant", "content": respuesta}
                
                # Guardar métricas de tokens y costo si están disponibles en el historial
                if hasattr(st.session_state.agent, "last_usage") and st.session_state.agent.last_usage:
                    u = st.session_state.agent.last_usage
                    c = st.session_state.agent.last_cost
                    if u:
                        model_name = getattr(st.session_state.agent, "last_model_used", "Unknown")
                        msg_data["metadata"] = {
                            "model": model_name,
                            "tokens": u,
                            "cost": c
                        }
                        st.caption(f"⚙️ **Model:** {model_name} | **Tokens:** {u['total_tokens']} (In: {u['prompt_tokens']} | Out: {u['completion_tokens']}) | **Cost:** ${c:.6f} USD")
                        
                st.session_state.messages.append(msg_data)
                
            except Exception as e:
                st.error(f"Internal Error: {e}")
