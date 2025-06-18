from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
import os, random
from dotenv import load_dotenv
from models.delete_request import DeleteRequest
from models.approve_request import ApproveRequest
from models.add_keywords_request import AddKeywordsRequest
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

        return RedirectResponse(url=f"{resp.data}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/images")
def list_images(
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=1000),
    labels: str = Query(None),        # Ejemplo: "fantasy,scifi"
    keywords: str = Query(None),      # Ejemplo: "romance,drama"
    deleted: bool = Query(False),
    keywords_mode: str = Query("or")  # Puede ser "or" o "and"
):
    start = (page - 1) * limit

    try:
        payload = {
            "kw_names": [k.strip() for k in keywords.split(",")] if keywords else None,
            "label_names": [l.strip() for l in labels.split(",")] if labels else None,
            "kw_mode": keywords_mode,
            "_deleted": deleted,
            "_limit": limit,
            "_offset": start
        }

        result = supabase.rpc("filter_images_general", payload).execute()
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
        # Si hay keywords → RPC
        if keywords:
            kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
            payload = {
                "mode": keywords_mode,
                "kw_names": kw_list,
                "_deleted": deleted,
            }
            resp = supabase.rpc("labels_for_keywords", payload).execute()
            return [row["name"] for row in resp.data]

        # Sin keywords → devolver todos los labels
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
                .eq("is_deleted", deleted) \
                .eq("status", "approved")
            result = query.execute()
            return {"count": result.count}

        # 🔹 KEYWORDS only (or/and)
        if keywords and not labels:
            keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]

            if keywords_mode == "or":
                query = supabase.table("images") \
                    .select("id, images_keywords!inner(keywords!inner(name))", count="exact") \
                    .in_("images_keywords.keywords.name", keyword_list) \
                    .eq("is_deleted", deleted) \
                    .eq("status", "approved")
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
                .eq("is_deleted", deleted) \
                .eq("status", "approved")
            result = query.execute()
            return {"count": result.count}

        # 🔹 BOTH: labels + keywords
        if labels and keywords:
            label_list = [l.strip() for l in labels.split(",") if l.strip()]
            keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]

            if keywords_mode == "or":
                query = supabase.table("images") \
                    .select("id, labels!inner(name), images_keywords!inner(keywords!inner(name))", count="exact") \
                    .in_("labels.name", label_list) \
                    .in_("images_keywords.keywords.name", keyword_list) \
                    .eq("is_deleted", deleted) \
                    .eq("status", "approved")
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
    

@app.get("/api/approve/images")
def get_approve_images(
    status: str = Query("pending"),
    id_label: int = Query(None),
    id_prompt: int = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
):
    try:
        offset = (page - 1) * limit

        resp = supabase.rpc(
            "approve_images_by_prompt_label",
            {
                "_status": status,
                "_id_label": id_label,
                "_id_prompt": id_prompt,
                "_limit": limit,
                "_offset": offset
            }
        ).execute()

        return resp.data

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@app.post("/api/approve/accept")
def approve_images(payload: ApproveRequest):
    try:
        resp = supabase.rpc(
            "set_images_status",
            {
                "_ids": payload.ids,
                "_status": "approved",
                "_ids_with_shade": payload.ids_with_shade
            }
        ).execute()

        return {"updated": [row["id"] for row in resp.data]}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/preapprove/accept")
def preapprove_images(payload: ApproveRequest):
    try:
        resp = supabase.rpc(
            "set_images_status",
            {"_ids": payload.ids, "_status": "preapproved"}
        ).execute()

        return {"updated": [row["id"] for row in resp.data]}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/approve/reject")
def reject_images(payload: ApproveRequest):
    try:
        resp = supabase.rpc(
            "set_images_status",
            {"_ids": payload.ids, "_status": "rejected"}
        ).execute()

        return {"updated": [row["id"] for row in resp.data]}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@app.post("/api/preapprove/reject")
def reject_images(payload: ApproveRequest):
    try:
        resp = supabase.rpc(
            "set_images_status",
            {"_ids": payload.ids, "_status": "prerejected"}
        ).execute()

        return {"updated": [row["id"] for row in resp.data]}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/approve/labels")
def get_approve_labels():
    try:
        resp = supabase.table("labels") \
            .select("id, name") \
            .execute()

        return [{"id": row["id"], "name": row["name"]} for row in resp.data]

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    

@app.get("/api/approve/prompts")
def get_prompts_approve(
    labels: str = Query(None),
    status: str = Query("pending"),
):
    try:
        label_list = (
            [l.strip() for l in labels.split(",") if l.strip()]
            if labels else None
        )

        payload = {
            "label_names": label_list,
            "_status": status
        }

        resp = supabase.rpc("prompts_for_labels_full", payload).execute()

        return [{"id": row["id"], "content": row["content"]} for row in resp.data]

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/approve/images_count")
def get_approve_images_count(
    status: str = Query("pending"),
    id_label: int = Query(None),
    id_prompt: int = Query(None),
):
    try:
        resp = supabase.rpc(
            "approve_images_count_by_prompt_label",
            {"_id_label": id_label, "_id_prompt": id_prompt, "_status": status}
        ).execute()

        return {"count": resp.data}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/assign_keywords/images")
def get_images_without_keywords(
    status: str = Query("approved"),
    id_label: int = Query(None),
    id_prompt: int = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
):
    try:
        offset = (page - 1) * limit

        resp = supabase.rpc(
            "approved_images_without_keywords",
            {
                "_status": status,
                "_id_label": id_label,
                "_id_prompt": id_prompt,
                "_limit": limit,
                "_offset": offset
            }
        ).execute()

        return resp.data

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@app.get("/api/assign_keywords/images_count")
def get_images_without_keywords_count(
    status: str = Query("approved"),
    id_label: int = Query(None),
    id_prompt: int = Query(None),
):
    try:
        resp = supabase.rpc(
            "count_images_without_keywords",
            {
                "_status": status,
                "_id_label": id_label,
                "_id_prompt": id_prompt
            }
        ).execute()

        return {"count": resp.data}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/assign_keywords/add")
def assign_keywords_to_image(payload: AddKeywordsRequest):
    try:
        print("\n✅ Payload recibido:")
        print(payload.dict())

        # 1. Parsear keywords
        keywords = [kw.strip().lower() for kw in payload.keywords.split(",") if kw.strip()]


        if not keywords or not payload.ids:
            print("❌ Error: keywords o ids vacíos")
            raise HTTPException(status_code=400, detail="Se requieren imágenes y keywords válidas.")
        
         # 2. Llamar a la función Supabase
        response = supabase.rpc("upsert_keywords_and_return_ids", {
            "keyword_names": keywords
        }).execute()


        keyword_ids = [kw["keyword_id"] for kw in response.data]


        # 3. Insertar todas las combinaciones en images_keywords
        insert_resp = supabase.rpc("assign_keywords_to_images", {
            "image_ids": payload.ids,
            "keyword_ids": keyword_ids
        }).execute()


        return {"message": "Keywords asignadas correctamente."}
    
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    

# ============Metrics============

@app.get("/api/images/metrics")
def get_metrics_generated(
    status: str = Query(None),
    label: str = Query(None)
    ):
    try:
        payload = {
            "_status": status,
            "_label": label
        }
        response = supabase.rpc("get_metrics", payload).execute()
        return response.data
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
