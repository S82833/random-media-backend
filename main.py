from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
import os, random
from dotenv import load_dotenv
from models.delete_request import DeleteRequest
import traceback
from collections import defaultdict

load_dotenv()

app = FastAPI()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://admin.media.authormedia.org",
                   "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def get_random_image(label: str):
    try:
        resp = supabase.rpc(
            "pick_image_url",
            {"_label_name": label}
        ).execute()

        if resp.data is None:
            raise HTTPException(status_code=404, detail="Label or images not found")

        return RedirectResponse(url=f"{resp.data}?download=1")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/images")
def list_images(
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    labels: str = Query(None), # es una lista separada por comas
    keywords: str = Query(None),  # e.g. "romance,drama"
    deleted: bool = Query(False),
    keywords_mode: str = Query(None)
):
    start = (page - 1) * limit
    end = start + limit - 1

    try:
        query = None

        # Caso: SOLO KEYWORDS
        
        if keywords:
            keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]

            if keywords_mode == "or":
                # 🔹 1 sola query con paginación
                query = supabase.table("images") \
                    .select("*, images_keywords!inner(keywords!inner(name))") \
                    .in_("images_keywords.keywords.name", keyword_list) \
                    .eq("is_deleted", deleted) \
                    .range(start, end)
                result = query.execute()
                return result.data

            elif keywords_mode == "and":
                payload = {
                    "kw_names": keyword_list,
                    "label_names": None,
                    "_deleted": deleted,
                    "_limit": limit,
                    "_offset": start
                }
                result = supabase.rpc("filter_images_by_keywords_and", payload).execute()
                return result.data
        # Caso: SOLO LABELS
        elif labels and not keywords: #si me pasan mas de 1 label con la nueva funcion tengo que regresar todo lo que contenga ambos
            label_list = [l.strip() for l in labels.split(",") if l.strip()]
            
            query = supabase.table("images") \
            .select("*, labels!inner(name)") \
            .in_("labels.name", label_list) \
            .eq("is_deleted", deleted) \
            .range(start, end)

            result = query.execute()
            return result.data
        
        elif labels and keywords:
            keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
            label_list = [l.strip() for l in labels.split(",") if l.strip()]

            if keywords_mode == "or":
                # 🔹 JOIN con keywords y labels, todo en una query
                query = supabase.table("images") \
                    .select("*, images_keywords!inner(keywords!inner(name)), labels!inner(name)") \
                    .in_("images_keywords.keywords.name", keyword_list) \
                    .in_("labels.name", label_list) \
                    .eq("is_deleted", deleted) \
                    .range(start, end)
                result = query.execute()
                return result.data

            elif keywords_mode == "and":
                # 🔹 Obtener imágenes por labels
                payload = {
                    "kw_names": keyword_list,
                    "label_names": label_list if labels else None,
                    "_deleted": deleted,
                    "_limit": limit,
                    "_offset": start
                }
                result = supabase.rpc("filter_images_by_keywords_and", payload).execute()
                return result.data
        else:
            query = supabase.table("images").select("*").eq("is_deleted", deleted).range(start, end)
            result = query.execute()
            return result.data
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/delete")
def delete_image(payload: DeleteRequest):
    try:
        resp = supabase.rpc(
            "set_images_deleted",
            {"_ids": payload.ids, "_flag": True}
        ).execute()

        touched = {row["id"] for row in resp.data}
        errores = list(set(payload.ids) - touched)

        return {
            "status": "partial_success" if errores else "ok",
            "deleted_ids": len(touched),
            "errors": errores
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/restore")
def delete_image(payload: DeleteRequest):
    try:
        resp = supabase.rpc(
            "set_images_deleted",
            {"_ids": payload.ids, "_flag": False}
        ).execute()

        touched = {row["id"] for row in resp.data}
        errores = list(set(payload.ids) - touched)

        return {
            "status": "partial_success" if errores else "ok",
            "restores_ids": len(touched),
            "errors": errores
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/labels")
def get_labels(
    keywords: str = Query(None),
    keywords_mode: str = Query("or"),
    deleted: bool = Query(False),
):
    try:
        # 👉 Si hay keywords → RPC
        if keywords:
            kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
            payload = {
                "mode": keywords_mode,
                "kw_names": kw_list,
                "_deleted": deleted,
            }
            resp = supabase.rpc("labels_for_keywords", payload).execute()
            return [row["name"] for row in resp.data]

        # 👉 Sin keywords → devolver todos los labels
        resp = supabase.table("labels").select("name").execute()
        return [row["name"] for row in resp.data]

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/keywords")
def get_keywords(
    labels: str = Query(None),
    deleted: bool = Query(False),
):
    try:
        # 👉 Si hay labels → RPC
        if labels:
            label_list = [l.strip() for l in labels.split(",") if l.strip()]
            payload = {
                "label_names": label_list,
                "_deleted": deleted,
            }
            resp = supabase.rpc("keywords_for_labels", payload).execute()
            return [row["name"] for row in resp.data]

        # 👉 Sin labels → todos los keywords
        resp = supabase.table("keywords").select("name").execute()
        return [row["name"] for row in resp.data]

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/images_count")
def get_images_count(
    labels: str = Query(None),
    keywords: str = Query(None),
    keywords_mode: str = Query("or"),
    deleted: bool = Query(False),
):
    try:
        if not labels and not keywords:
            # 🔹 Caso sin filtros: contar todo
            query = supabase.table("images") \
                .select("id", count="exact") \
                .eq("is_deleted", deleted)
            result = query.execute()
            return {"count": result.count}

        # 🔹 KEYWORDS only (or/and)
        if keywords and not labels:
            keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]

            if keywords_mode == "or":
                query = supabase.table("images") \
                    .select("id, images_keywords!inner(keywords!inner(name))", count="exact") \
                    .in_("images_keywords.keywords.name", keyword_list) \
                    .eq("is_deleted", deleted)
                result = query.execute()
                return {"count": result.count}
            
            elif keywords_mode == "and":
                payload = {
                    "kw_names": keyword_list,
                    "label_names": None,
                    "_deleted": deleted
                }
                result = supabase.rpc("filter_images_by_keywords_and_count", payload).execute()
                return {"count": result.data}

        # 🔹 LABELS only
        if labels and not keywords:
            label_list = [l.strip() for l in labels.split(",") if l.strip()]
            query = supabase.table("images") \
                .select("id, labels!inner(name)", count="exact") \
                .in_("labels.name", label_list) \
                .eq("is_deleted", deleted)
            result = query.execute()
            return {"count": result.count}

        # 🔹 BOTH: labels + keywords
        if labels and keywords:
            label_list = [l.strip() for l in labels.split(",") if l.strip()]
            keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
            keyword_set = set(keyword_list)

            if keywords_mode == "or":
                query = supabase.table("images") \
                    .select("id, labels!inner(name), images_keywords!inner(keywords!inner(name))", count="exact") \
                    .in_("labels.name", label_list) \
                    .in_("images_keywords.keywords.name", keyword_list) \
                    .eq("is_deleted", deleted)
                result = query.execute()
                return {"count": result.count}

            elif keywords_mode == "and":
                payload = {
                    "kw_names": keyword_list,
                    "label_names": label_list,
                    "_deleted": deleted
                }
                result = supabase.rpc("filter_images_by_keywords_and_count", payload).execute()
                return {"count": result.data}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})