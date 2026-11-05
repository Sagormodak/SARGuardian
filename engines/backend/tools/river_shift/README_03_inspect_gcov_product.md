# 03 · Inspect NISAR GCOV HDF5

## Purpose
Read the HDF5 product inventory and identify the available calibrated GCOV diagonal covariance layers before extracting any data.

## NASA challenge relevance
NISAR GCOV provides geocoded, radiometrically and terrain-corrected gamma-nought power measurements. The diagonal covariance terms are real-valued backscatter intensity layers suitable for intensity-based surface-change screening.

## Inputs
- One downloaded NISAR Level-2 GCOV HDF5 file.
- GDAL 3.13.0 or newer with its HDF5 driver.

## Method
1. Run gdalinfo --version and require GDAL 3.13.0 or newer.
2. Run gdalinfo -json on the exact HDF5 file.
3. Inspect the SUBDATASETS inventory.
4. List only the available diagonal real-valued covariance terms: HHHH, HVHV, VVVV, VHVH, RHRH and RVRV.
5. Record the spatial size, CRS and GDAL version.

## Reproduce
    python inspect_gcov_product.py --product data/raw/EXACT_GRANULE.h5

The file name is an example placeholder. Use the exact file from README_02.

## Outputs
- A .gcov_inventory.json file listing available diagonal terms and subdataset identifiers.

## Acceptance tests
- A missing product path fails.
- GDAL versions older than 3.13 fail with an explicit message.
- A non-GCOV HDF5 file without diagonal terms is rejected.
- The inventory never assumes that every polarization exists.
- The selected layer must later be checked against all other dates.

## Scientific limitations
- Product inventory is not a classification.
- Available polarization depends on the acquisition mode.
- Frequency A and Frequency B have different sampling and must not be silently mixed.
- Most land Frequency-A GCOV products are posted at 10 m or 20 m; Frequency-B products are 80 m. Use the exact pixel spacing reported by each product.

## AI reviewer checklist
- Confirm GDAL version requirement.
- Confirm that only real-valued diagonal covariance terms are listed.
- Confirm the script does not fabricate absent polarizations.
- Confirm product path and inventory provenance are stored.

## Primary references
- NISAR GCOV guide: https://nisar-docs.asf.alaska.edu/gcov/
- NISAR HDF5 guide: https://nisar-docs.asf.alaska.edu/data-format/
- GDAL NISAR transformation guide: https://nisar-docs.asf.alaska.edu/using-nisar-data/using-gdal/
