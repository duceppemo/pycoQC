# pycoQC Changelog

### 18/11/2023 v-3.0.0.0

* Added support for Fastq input.
* If Fastq provided, %GC graphs are added
* Added support for BAM input if Doraro is used to basecall
* Added support for pod5 input
* Improved support for barcodes

### 11/10/2019 v-2.5.0.17

* Style update to comply with codacity
* Update summary table functions and split into 3 Run, Basecall and align

### 11/10/2019 v-2.5.0.14

* Add min_pass_len option to specify a minimal read length to be "pass"
* Update pycoQC usage doc and fix notebooks broken links

### 10/10/2019 v-2.5.0.12

* Start documenting changelog
* Change alignment score for identity frequency
* Reorganise documentation directory
* File names in HTML reports are now absolute paths
* Fix errors in Fast5_to_seq_summary
