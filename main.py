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
    allow_origins=["https://admin.media.authormedia.org",],
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
    result_url = f'{image["image_url"]}?download=1'
    return RedirectResponse(url=result_url)

@app.get("/api/images")
def list_images(
    page: int = Query(1, ge=1),
    limit: int = Query(10000, ge=1, le=10000),
    label: str = Query(None),
    search: str = Query(None),
    deleted: bool = Query(False),
):
    start = (page - 1) * limit
    end = start + limit - 1

    query = supabase.table("images") \
        .select("*") 
    
    if deleted:
        query = query.eq("is_deleted", deleted)

    if label:
        query = query.eq("label", label)

    if search:
        query = query.ilike("image_url", f"%{search}%")

    query = query.range(start, end)

    try:
        result = query.execute()
        return result.data
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

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

@app.post("/api/restore")
def restore_image(payload: DeleteRequest):
    errores = []
    restaurados = 0

    for id in payload.ids:
        try:
            response = supabase.table("images").update({"is_deleted": False}).eq("id", id).execute()
            if response.data:
                restaurados += 1
            else:
                errores.append(id)

        except Exception as e:
            errores.append({"id": id, "error": str(e)})

    if errores:
        return {
            "status": "partial_success",
            "restored_ids": restaurados,
            "errors": errores
        }

    return {
        "status": "ok",
        "restored_ids": restaurados
    }

@app.get("/api/labels")
def get_labels():
    result = supabase.rpc("get_unique_labels", {}).execute()
    if result.data:
        return result.data
    return []

@app.get("/api/images_count")
def get_images_count(
    label: str = Query(None),
    search: str = Query(None),
    deleted: bool = Query(False),
):
    query = supabase.table("images").select("id", count="exact")

    if deleted:
        query = query.eq("is_deleted", deleted)

    if label:
        query = query.eq("label", label)

    if search:
        query = query.ilike("image_url", f"%{search}%")

    try:
        result = query.execute()
        return {"count": result.count}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
