"""Commercial Insurance Wording Comparator API; the app is in main.py."""


def main() -> None:
    """Command `commercial-insurance-wording-comparator`: serve the API on port 8000 (HOST and PORT override)."""
    import os

    import uvicorn

    uvicorn.run(
        "commercial_insurance_wording_comparator.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
