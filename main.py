from fastapi import FastAPI, Query
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
def get_random_image(label: str):
    try:
        # 1. Buscar el ID del label por nombre
        label_response = supabase.table("labels").select("id").eq("name", label).execute()
        if not label_response.data:
            return JSONResponse(status_code=404, content={"error": f"Label '{label}' not found."})

        label_id = label_response.data[0]["id"]

        # 2. Buscar imagen con menos usos para ese label_id
        result = supabase.table("images") \
            .select("*") \
            .eq("id_label", label_id) \
            .eq("is_deleted", False) \
            .order("viewed_count") \
            .order("created_at") \
            .limit(10) \
            .execute()

        if not result.data:
            return JSONResponse(status_code=404, content={"error": "No images found for this label."})

        # 3. Seleccionar una imagen aleatoria
        image = random.choice(result.data)

        # 4. Actualizar viewed_count usando función RPC
        try:
            supabase.rpc("increment_viewed_count", {"image_id": image["id"]}).execute()
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": "Error al actualizar viewed_count."})

        # 5. Redirigir a la imagen
        result_url = f'{image["image_url"]}?download=1'
        return RedirectResponse(url=result_url)

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/images")
def list_images(
    page: int = Query(1, ge=1),
    limit: int = Query(10000, ge=1, le=10000),
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
            keyword_set = set(keyword_list)

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
                # 🔹 1. Hacer JOIN para traer todas las combinaciones
                raw = supabase.table("images") \
                    .select("id, images_keywords!inner(keywords!inner(name))") \
                    .in_("images_keywords.keywords.name", keyword_list) \
                    .eq("is_deleted", deleted) \
                    .limit(100000) \
                    .execute()

                # 🔹 2. Agrupar y filtrar en Python
                image_keyword_map = defaultdict(set)
                for row in raw.data:
                    image_id = row["id"]
                    for kw in row.get("images_keywords", []):
                        if kw.get("keywords"):
                            image_keyword_map[image_id].add(kw["keywords"]["name"])

                filtered_ids = [
                    image_id for image_id, kws in image_keyword_map.items()
                    if keyword_set.issubset(kws)
                ]

                if not filtered_ids:
                    return []

                # 🔹 3. Hacer query final con paginación
                query = supabase.table("images") \
                    .select("*") \
                    .in_("id", filtered_ids) \
                    .eq("is_deleted", deleted) \
                    .range(start, end)

                result = query.execute()
                return result.data
        # Caso: SOLO LABELS
        elif labels and not keywords:
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
            keyword_set = set(keyword_list)

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
                label_response = supabase.table("labels").select("id").in_("name", label_list).execute()
                label_ids = [row["id"] for row in label_response.data]
                if not label_ids:
                    return []

                images_from_labels = supabase.table("images") \
                    .select("id") \
                    .in_("id_label", label_ids) \
                    .eq("is_deleted", deleted) \
                    .limit(100000) \
                    .execute()
                image_ids_from_labels = [row["id"] for row in images_from_labels.data]
                if not image_ids_from_labels:
                    return []

                # 🔹 JOIN con images_keywords + keywords
                raw = supabase.table("images") \
                    .select("id, images_keywords!inner(keywords!inner(name))") \
                    .in_("id", image_ids_from_labels) \
                    .in_("images_keywords.keywords.name", keyword_list) \
                    .eq("is_deleted", deleted) \
                    .limit(100000) \
                    .execute()

                image_keyword_map = defaultdict(set)
                for row in raw.data:
                    image_id = row["id"]
                    for kw in row.get("images_keywords", []):
                        if kw.get("keywords"):
                            image_keyword_map[image_id].add(kw["keywords"]["name"])

                image_ids_filtered = [
                    image_id for image_id, kw_set in image_keyword_map.items()
                    if keyword_set.issubset(kw_set)
                ]
                if not image_ids_filtered:
                    return []

                query = supabase.table("images") \
                    .select("*") \
                    .in_("id", image_ids_filtered) \
                    .eq("is_deleted", deleted) \
                    .range(start, end)
                result = query.execute()
                return result.data
        else:
            query = supabase.table("images").select("*").eq("is_deleted", deleted).range(start, end)
            result = query.execute()
            return result.data
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/delete")
def delete_image(payload: DeleteRequest):
    errores = []
    borrados = 0
    data = []

    for id in payload.ids:    
        try:
            response = supabase.table("images").update({"is_deleted": True}).eq("id", id).execute()
            if response.data:
                borrados += 1
            else:
                errores.append(id)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

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
def get_labels(
    keywords: str = Query(None),
    keywords_mode: str = Query("or"),
    deleted: bool = Query(False),
):
    try:
        if keywords:
            keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
            keyword_set = set(keyword_list)

            if keywords_mode == "or":
                # 🔹 JOIN directo: buscar labels de imágenes que tengan al menos 1 keyword
                result = supabase.table("images") \
                    .select("id_label, images_keywords!inner(keywords!inner(name))") \
                    .in_("images_keywords.keywords.name", keyword_list) \
                    .eq("is_deleted", deleted) \
                    .limit(100000) \
                    .execute()

                label_ids = {row["id_label"] for row in result.data if row.get("id_label")}
                if not label_ids:
                    return []

                labels_response = supabase.table("labels").select("name").in_("id", list(label_ids)).execute()
                return [row["name"] for row in labels_response.data]

            elif keywords_mode == "and":
                # 🔹 JOIN para obtener todas las combinaciones
                raw = supabase.table("images") \
                    .select("id, id_label, images_keywords!inner(keywords!inner(name))") \
                    .in_("images_keywords.keywords.name", keyword_list) \
                    .eq("is_deleted", deleted) \
                    .limit(100000) \
                    .execute()

                # Agrupar keywords por imagen
                image_map = {}
                for row in raw.data:
                    image_id = row["id"]
                    label_id = row["id_label"]
                    if not label_id:
                        continue
                    if image_id not in image_map:
                        image_map[image_id] = {
                            "label_id": label_id,
                            "keywords": set()
                        }
                    for kw in row["images_keywords"]:
                        if kw.get("keywords"):
                            image_map[image_id]["keywords"].add(kw["keywords"]["name"])

                # Filtrar imágenes con TODOS los keywords
                matching_label_ids = {
                    data["label_id"]
                    for data in image_map.values()
                    if keyword_set.issubset(data["keywords"])
                }

                if not matching_label_ids:
                    return []

                labels_response = supabase.table("labels").select("name").in_("id", list(matching_label_ids)).execute()
                return [row["name"] for row in labels_response.data]

        else:
            # 🔹 Sin filtro de keywords → labels de todas las imágenes no eliminadas
            query = supabase.table("labels").select("*")
            result = query.execute()
            return [row["name"] for row in result.data]

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/keywords")
def get_keywords(
    labels: str = Query(None),
    deleted: bool = Query(False),
):
    try:
        if labels:
            label_list = [l.strip() for l in labels.split(",") if l.strip()]

            # 1. JOIN desde images -> images_keywords -> keywords
            response = supabase.table("images") \
                .select("images_keywords!inner(keywords!inner(name))") \
                .in_("labels.name", label_list) \
                .eq("is_deleted", deleted) \
                .limit(100000) \
                .execute()

            keyword_names = set()

            for row in response.data:
                for kw in row.get("images_keywords", []):
                    keyword = kw.get("keywords", {}).get("name")
                    if keyword:
                        keyword_names.add(keyword)

            return list(keyword_names)

        else:
            # Si no se pasaron labels, devolver todos los keywords no eliminados
            keywords_response = supabase.table("keywords").select("name").limit(100000).execute()
            keyword_names = list({row["name"] for row in keywords_response.data})
            return keyword_names

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
            keyword_set = set(keyword_list)

            if keywords_mode == "or":
                query = supabase.table("images") \
                    .select("id, images_keywords!inner(keywords!inner(name))", count="exact") \
                    .in_("images_keywords.keywords.name", keyword_list) \
                    .eq("is_deleted", deleted)
                result = query.execute()
                return {"count": result.count}
            
            elif keywords_mode == "and":
                # 1. Traer todas las combinaciones
                raw = supabase.table("images") \
                    .select("id, images_keywords!inner(keywords!inner(name))") \
                    .in_("images_keywords.keywords.name", keyword_list) \
                    .eq("is_deleted", deleted) \
                    .limit(100000) \
                    .execute()

                # 2. Agrupar por imagen y filtrar en Python
                image_keyword_map = defaultdict(set)
                for row in raw.data:
                    image_id = row["id"]
                    for kw in row.get("images_keywords", []):
                        if kw.get("keywords"):
                            image_keyword_map[image_id].add(kw["keywords"]["name"])

                filtered_ids = [
                    image_id for image_id, kws in image_keyword_map.items()
                    if keyword_set.issubset(kws)
                ]

                return {"count": len(filtered_ids)}

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
                # 🔹 1. Obtener imágenes por label
                label_ids_resp = supabase.table("labels").select("id").in_("name", label_list).execute()
                label_ids = [row["id"] for row in label_ids_resp.data]
                if not label_ids:
                    return {"count": 0}

                image_resp = supabase.table("images") \
                    .select("id") \
                    .in_("id_label", label_ids) \
                    .eq("is_deleted", deleted) \
                    .limit(100000).execute()

                image_ids = [row["id"] for row in image_resp.data]
                if not image_ids:
                    return {"count": 0}

                # 🔹 2. Hacer join por keywords sobre esas imágenes
                raw = supabase.table("images") \
                    .select("id, images_keywords!inner(keywords!inner(name))") \
                    .in_("id", image_ids) \
                    .in_("images_keywords.keywords.name", keyword_list) \
                    .eq("is_deleted", deleted) \
                    .limit(100000).execute()

                image_keyword_map = defaultdict(set)
                for row in raw.data:
                    image_id = row["id"]
                    for kw in row.get("images_keywords", []):
                        if kw.get("keywords"):
                            image_keyword_map[image_id].add(kw["keywords"]["name"])

                filtered_ids = [
                    image_id for image_id, kws in image_keyword_map.items()
                    if keyword_set.issubset(kws)
                ]

                return {"count": len(filtered_ids)}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})