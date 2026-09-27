"""
main.py
-------
نقطة تشغيل المشروع. يكفي تنفيذ: python main.py
uvicorn يشغّل webhook_server:app الذي بدوره يشغّل بوت التليجرام
تلقائياً عند الإقلاع (انظر lifespan داخل webhook_server.py).
"""

import uvicorn
from config import settings

if __name__ == "__main__":
    uvicorn.run(
        "webhook_server:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=False,
    )
