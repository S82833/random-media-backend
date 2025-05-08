from fastapi import FastAPI, Query
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
import os, random
from dotenv import load_dotenv
from models.delete_request import DeleteRequest
import traceback

load_dotenv()

app = FastAPI()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], #cambiar esto por https://admin.media.authormedia.org
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def get_random_image(label: str):
    # 1. Primero buscamos la imagen con menos cantidad de usos
    result = supabase.table("images") \
        .select("*") \
        .eq("label", label) \
        .eq("is_deleted", False) \
        .order("viewed_count") \
        .order("created_at") \
        .limit(10) \
        .execute()
    
    if not result.data:
        return JSONResponse(status_code=404, content={"error": "No images found for this label."})
    
    image = random.choice(result.data)
    # 2. Actualizamos la cantidad de veces que se ha visto la imagen
    try:    
        supabase.rpc("increment_viewed_count", {"image_id": image["id"]}).execute()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "Error al actualizar viewed_count."})


    # 3. Devolvemos la URL de la imagen
    return RedirectResponse(url=image["image_url"])

@app.get("/api/images")
def list_images(label: str = Query(None)):
    query = supabase.table("images").select("*").eq("is_deleted", False)
    if label:
        query = query.eq("label", label)
    result = query.execute()
    return result.data

@app.post("/api/delete")
def delete_image(payload: DeleteRequest):
    errores = []
    borrados = 0

    for id in payload.ids:
        try:
            response = supabase.table("images").update({"is_deleted": True}).eq("id", id).execute()
            if response.data:
                borrados += 1
            else:
                errores.append(id)

        except Exception as e:
            errores.append({"id": id, "error": str(e)})

    if errores:
        return {
            "status": "partial_success",
            "deleted_ids": borrados,
            "errors": errores
        }

    return {
        "status": "ok",
        "deleted_ids": borrados
    }