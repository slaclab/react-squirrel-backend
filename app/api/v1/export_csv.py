import io
import csv
from datetime import datetime

from fastapi import Depends, Response, APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.pv_service import PVService
from app.services.tag_service import TagService

router = APIRouter(prefix="/export", tags=["Export"])


@router.get("/export_csv")
async def export_database_csv(db: AsyncSession = Depends(get_db)):
    """
    Export PVs and Tags to CSV format.
    Returns two CSV files: one for PVs and one for Tags.
    """
    pv_service = PVService(db)
    tag_service = TagService(db)

    # ======= Export PVs =======
    pvs_result = await pv_service.search_paged(page_size=10000)

    # Generate PVs CSV
    pv_output = io.StringIO()
    pv_writer = csv.writer(pv_output)

    # write PV headers for the CSV
    pv_headers = [
        "ID",
        "Setpoint Address",
        "Readback Address",
        "Config Address",
        "Device",
        "Description",
        "Abs Tolerance",
        "Rel Tolerance",
        "Read Only",
    ]
    pv_writer.writerow(pv_headers)

    # Write PV data into rows for the CSV
    for pv in pvs_result.results:
        row = [
            pv.id,
            pv.setpointAddress,
            pv.readbackAddress,
            pv.configAddress,
            pv.device,
            pv.description,
            pv.absTolerance,
            pv.relTolerance,
            pv.readOnly,
        ]
        pv_writer.writerow(row)

    # Prepare the PV rows to put in the CSV file
    pv_content = pv_output.getvalue()

    # ======= Export Tags =======
    tag_groups = await tag_service.get_all_groups_summary()

    # Generate Tags CSV
    tag_output = io.StringIO()
    tag_writer = csv.writer(tag_output)

    # Write Tag headers for the CSV
    tag_writer.writerow(["Group ID", "Group Name", "Group Description", "Tag ID", "Tag Name", "Tag Description"])

    # Write Tag data into rows for the CSV
    for group in tag_groups:
        for tag in group.tags:
            tag_writer.writerow([group.id, group.name, group.description, tag.id, tag.name, tag.description])

    # Prepare the Tag rows to put in the CSV file
    tag_content = tag_output.getvalue()

    # Create a combined response with both CSV files
    combined_content = f"=== PVs Export ===\n{pv_content}\n\n=== Tags Export ===\n{tag_content}"

    # Return as a downloadable CSV file
    return Response(
        content=combined_content,
        media_type="csv",
        headers={
            "Content-Disposition": f"attachment; filename=database_export_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"
        },
    )
