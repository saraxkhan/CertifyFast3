import pandas as pd
import os


def load_data(path: str) -> pd.DataFrame:
    """
    Load a CSV or Excel data file into a DataFrame.

    Handles:
      - .csv files that are actually Excel format (common Canva/Excel export issue)
      - .xlsx and .xls files
      - Whitespace in column names and string cell values
      - Empty rows (drops them)

    Raises ValueError with a clear message on failure.
    """
    ext = os.path.splitext(path)[1].lower()

    df = None

    if ext == ".csv":
        # Try CSV first; if it fails or produces garbage, try Excel
        try:
            df = pd.read_csv(path, engine="python")
            # Sanity check: if we got only 1 column and it looks like binary,
            # it's probably actually an xlsx file
            if len(df.columns) == 1 and df.columns[0].startswith("PK"):
                raise ValueError("File is actually Excel format")
        except Exception:
            # Fallback: try reading as Excel
            try:
                df = pd.read_excel(path, engine="openpyxl")
            except Exception as e:
                raise ValueError(
                    f"Could not read '{os.path.basename(path)}'. "
                    f"It appears to be neither valid CSV nor Excel. ({e})"
                )
    elif ext in (".xlsx", ".xls"):
        try:
            df = pd.read_excel(path, engine="openpyxl")
        except Exception as e:
            raise ValueError(
                f"Could not read '{os.path.basename(path)}' as Excel. ({e})"
            )
    else:
        raise ValueError(
            f"Unsupported file type '{ext}'. Please upload a .csv or .xlsx file."
        )

    # ── Clean up ──
    # Strip whitespace from column names
    df.columns = [str(c).strip() for c in df.columns]

    # Strip whitespace from all string columns
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str).str.strip()

    # Drop completely empty rows
    df.dropna(how="all", inplace=True)
    df.reset_index(drop=True, inplace=True)

    if len(df) == 0:
        raise ValueError("The data file is empty — no rows to generate certificates from.")

    return df
