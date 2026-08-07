"""Sample / fallback data for widget data sources.

Used when external APIs are unreachable (dev, offline builds, tests).
"""
from __future__ import annotations

# Real SRR30334525 metadata fetched from NCBI SRA runinfo API.
# Zea mays RNA-Seq, Illumina NovaSeq 6000, PRJNA1150623.
SRA_SRR30334525: dict[str, str] = {
    "Run": "SRR30334525",
    "ReleaseDate": "2024-11-19 15:05:31",
    "LoadDate": "2024-08-21 20:37:24",
    "spots": "385,735,859",
    "bases": "116,492,229,418",
    "spots_with_mates": "385,735,859",
    "avgLength": "302",
    "size_MB": "43,267",
    "download_path": (
        "https://sra-downloadb.be-md.ncbi.nlm.nih.gov/sos11/sra-pub-zq-1140/"
        "SRR030/30334/SRR30334525/SRR30334525.lite.1"
    ),
    "Experiment": "SRX25794639",
    "LibraryName": "GSM8476438",
    "LibraryStrategy": "RNA-Seq",
    "LibrarySelection": "cDNA",
    "LibrarySource": "TRANSCRIPTOMIC",
    "LibraryLayout": "PAIRED",
    "InsertSize": "0",
    "InsertDev": "0",
    "Platform": "ILLUMINA",
    "Model": "Illumina NovaSeq 6000",
    "SRAStudy": "SRP527922",
    "BioProject": "PRJNA1150623",
    "Study_Pubmed_id": "4",
    "ProjectID": "1150623",
    "Sample": "SRS22426140",
    "BioSample": "SAMN43293205",
    "SampleType": "simple",
    "TaxID": "4577",
    "ScientificName": "Zea mays",
    "SampleName": "GSM8476438",
    "CenterName": "UNIVERSITY OF MICHIGAN",
    "Submission": "SRA1953259",
    "Consent": "public",
    "sra_url": "https://trace.ncbi.nlm.nih.gov/Traces/sra?run=SRR30334525",
}

# Soybean (Glycine max) exemplar SRA entries for demo / seed data.
SOYBEAN_SRA_SAMPLES: list[dict[str, str]] = [
    {
        "Run": "SRR29196978",
        "BioProject": "PRJNA1019865",
        "ScientificName": "Glycine max",
        "LibraryStrategy": "RNA-Seq",
        "Platform": "ILLUMINA",
        "Model": "Illumina NovaSeq 6000",
        "spots": "45,231,780",
        "bases": "6,784,767,000",
        "avgLength": "150",
        "size_MB": "2,541",
        "ReleaseDate": "2024-05-20",
        "CenterName": "University of Illinois",
        "sra_url": "https://trace.ncbi.nlm.nih.gov/Traces/sra?run=SRR29196978",
    },
    {
        "Run": "SRR29196979",
        "BioProject": "PRJNA1019865",
        "ScientificName": "Glycine max",
        "LibraryStrategy": "RNA-Seq",
        "Platform": "ILLUMINA",
        "Model": "Illumina NovaSeq 6000",
        "spots": "42,118,932",
        "bases": "6,317,839,800",
        "avgLength": "150",
        "size_MB": "2,368",
        "ReleaseDate": "2024-05-20",
        "CenterName": "University of Illinois",
        "sra_url": "https://trace.ncbi.nlm.nih.gov/Traces/sra?run=SRR29196979",
    },
]

__all__ = ["SRA_SRR30334525", "SOYBEAN_SRA_SAMPLES"]
