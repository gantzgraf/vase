from .vcf_filter import VcfFilter

clinvar_path_annot = ['Likely_pathogenic', 'Pathogenic', '4', '5']


class dbSnpFilter(VcfFilter):
    '''
        An object that filters VCF records based on variant data in a
        dbSNP VCF file.
    '''

    def __init__(self, vcf, prefix='VASE_dbSNP', logger=None, freq=None,
                 min_freq=None, build=None, max_build=None,
                 clinvar_path=False, no_walk=False, force_walk=False,
                 skip_svs=True):
        '''
            Initialize object with a dbSNP VCF file and optional filtering
            arguments.

            Args:
                vcf:          VCF containing variants to use to filter
                              or annotate records.

                prefix:       Prefix to prepend to added INFO field
                              annotations. Default = VASE_dbSNP.

                freq:         Filter alleles if dbSNP allele frequency
                              is greater than this value. Optional.

                min_freq:     Filter alleles if dbSNP allele frequency
                              is less than this value. Optional.

                build:        Filter alleles if dbSNP allele build is
                              lower (earlier) than this value. Optional.

                max_build:    Filter alleles if dbSNP allele build is
                              higher (later) than this value. Optional.

                clinvar_path: Keep alleles (overriding any filtering
                              based on freq/min_freq, build/min_build
                              values) if matching allele has a CLNSIG
                              value of 4 or 5 (corresponding to 'likely
                              pathogenic' or 'pathogenic' ClinVar
                              annotations).

                no_walk:      See VcfFilter documentation.

                force_walk:   See VcfFilter documentation.

                skip_svs:     See VcfFilter documentation.

        '''

        self.build_fields = {}
        self.clinvar_fields = {}
        self.build = build
        self.max_build = max_build
        self.clinvar_path = clinvar_path
        super().__init__(vcf, prefix, logger=logger, freq=freq,
                         min_freq=min_freq, no_walk=no_walk,
                         force_walk=force_walk, skip_svs=skip_svs)
        if self.build is not None and self.max_build is not None:
            if self.build > self.max_build:
                raise RuntimeError("build argument must not be greater than " +
                                   "max_build argument")

    def annotate_and_filter_record(self, record):
        filter_alleles = []
        keep_alleles = []
        matched_alleles = []
        annotations = []
        hits = self.get_overlapping_records(record)
        all_annots = set()  # all fields added, may not be present for all ALTs
        for i in range(len(record.DECOMPOSED_ALLELES)):
            filt, keep, matched, annot = self._compare_snp_values(
                                            record.DECOMPOSED_ALLELES[i], hits)
            filter_alleles.append(filt)
            keep_alleles.append(keep)
            matched_alleles.append(matched)
            annotations.append(annot)
            all_annots.update(annot.keys())
        info_to_add = {}
        rsids = []
        for f in all_annots:
            f_name = self.prefix + "_" + f
            info_to_add[f_name] = []
            for i in range(len(record.DECOMPOSED_ALLELES)):
                if f in annotations[i]:
                    a_val = annotations[i][f]
                    if f == 'RSID':
                        rsids.append(a_val)
                else:
                    a_val = None
                info_to_add[f_name].append(a_val)
        if rsids:
            record.add_ids(rsids)
        if info_to_add:
            record.add_info_fields(info_to_add)
        return filter_alleles, keep_alleles, matched_alleles

    def _compare_snp_values(self, alt_allele, snp_list):
        # flag indicating allele should be filtered
        do_filter = False
        # flag to indicate that should be kept, for overriding do_filter in
        # downstream filters
        do_keep = False
        annot = {}
        matched = False
        for snp in snp_list:
            for i in range(len(snp.DECOMPOSED_ALLELES)):
                if alt_allele == snp.DECOMPOSED_ALLELES[i]:
                    # no point attempting to use snp.parsed_info_fields() for
                    # these fields as they are not set to appropriate types
                    matched = True
                    annot['RSID'] = snp.id
                    for f in self.freq_fields:
                        if f not in snp.info:
                            continue
                        if f == 'CAF' or f == 'TOPMED':
                            if snp.info[f][i+1] == '.':
                                val = None
                            else:
                                val = float(snp.info[f][i+1])
                            annot[f] = val
                            if val is None:
                                continue
                            if self.freq is not None:
                                if val >= self.freq:
                                    do_filter = True
                            if self.min_freq is not None:
                                if val < self.min_freq:
                                    do_filter = True
                        elif (f == 'COMMON' and
                              len(snp.DECOMPOSED_ALLELES) == 1):
                            # COMMON=1 indicates > 1% in 1000 genomes but does
                            # not indicate which allele(s) if multiple ALTs
                            annot[f] = snp.info[f]
                            if self.freq is not None and self.freq <= 0.01:
                                if snp.info[f] == 1:
                                    do_filter = True
                            if (self.min_freq is not None
                                    and self.min_freq <= 0.01):
                                if snp.info[f] == 0:
                                    do_filter = True
                        elif (f == 'G5A' or f == 'G5' and
                              len(snp.DECOMPOSED_ALLELES) == 1):
                            # FLAGS: >=5% in 1kg or >=5% in pop from 1kg
                            annot[f] = 1
                            if self.freq is not None and self.freq <= 0.05:
                                if snp.info[f]:
                                    do_filter = True
                            if (self.min_freq is not None
                                    and self.min_freq <= 0.05):
                                if snp.info[f]:
                                    do_filter = False

                    for f in self.build_fields:
                        if f not in snp.info:
                            continue
                        annot[f] = snp.info[f]
                        if (self.build is not None and
                                snp.info[f] < self.build):
                            do_filter = True
                        if (self.max_build is not None and
                                snp.info[f] > self.max_build):
                            do_filter = True

                    if 'CLNALLE' in snp.info:
                        # the old clinvar annotations are done in non-standard
                        # way, giving indexes of relevant alleles in CLNALLE
                        # and keeping other annotations in the same order
                        cln_idx = i + 1
                        if cln_idx in snp.info['CLNALLE']:
                            j = snp.info['CLNALLE'].index(cln_idx)
                            for f in self.clinvar_fields:
                                if f == 'CLNALLE':
                                    continue
                                try:
                                    sig = snp.info[f][j]
                                except IndexError:
                                    if f == 'GENEINFO':
                                        sig = snp.info[f]
                                    else:
                                        raise
                                annot[f] = sig
                                if self.clinvar_path and f == 'CLNSIG':
                                    if ([i for i in clinvar_path_annot if i
                                         in sig.split('|')]):
                                        # keep anything lbld path or likely
                                        do_filter = False
                                        do_keep = True
                    elif len(snp.DECOMPOSED_ALLELES) == 1:
                        if 'CLNSIG' in snp.info:
                            annot['CLNSIG'] = snp.info['CLNSIG'][0]
                            if ([i for i in clinvar_path_annot if i in
                                 annot['CLNSIG'].split('|')]):
                                # keep anything with path or likely label
                                do_filter = False
                                do_keep = True
                if matched:
                    break
        return (do_filter, do_keep, matched, annot)

    def get_annot_fields(self):
        '''
            Creates dicts of INFO field names to dicts of 'type',
            'number' and 'description' as found in the VCF metadata for
            known dbSNP INFO field names for frequency (freq_fields),
            dbSNP build versions (build_fields) and ClinVar
            (clinvar_fields).
        '''

        freq_fields = ("CAF", "G5A", "G5", "COMMON", "TOPMED")
        clinvar_fields = ("CLNSIG", "CLNALLE", "CLNDBN", "CLNDSDBID",
                          "CLNHGVS", "GENEINFO")
        build = ("dbSNPBuildID",)
        for f in freq_fields:
            if f in self.vcf.header.info:
                self.freq_fields[f] = self._meta2dict(self.vcf.header.info[f])
        for f in clinvar_fields:
            if f in self.vcf.header.info:
                self.clinvar_fields[f] = self._meta2dict(
                    self.vcf.header.info[f])
        for f in build:
            if f in self.vcf.header.info:
                self.build_fields[f] = self._meta2dict(self.vcf.header.info[f])
        # raise a RuntimeError if no freq fields if filtering on frequency or
        # if no build fields if filtering on build, but let lack of ClinVar
        # fields slide as clinvar filtering may be occuring with a separate
        # ClinVar file
        if not self.freq_fields and not self.clinvar_path and (
                self.freq is not None or self.min_freq is not None):
            raise RuntimeError("ERROR: no frequency fields identified in " +
                               "dbSNP VCF header for file '{}'. " .format(
                                   self.vcf.filename) + "Unable to use freq/" +
                               "min_freq arguments for variant filtering.")

        if not self.build_fields and not self.clinvar_path and (
                self.build is not None or self.max_build is not None):
            raise RuntimeError("ERROR: no dbSNPBuildID field identified in " +
                               "dbSNP VCF header for file '{}'. "
                               .format(self.vcf.filename) +
                               "Unable to use build/max_build arguments for " +
                               "variant filtering.")

    def create_header_fields(self):
        '''
            Create dict entries for all INFO fields added by this
            instance, suitable for adding to a VcfHeader object.
        '''

        for f, v in self.freq_fields.items():
            if f == 'CAF' or f == 'TOPMED':
                v['type'] = 'Float'
            self._make_metadata(f, v)
        for f, v in self.build_fields.items():
            self._make_metadata(f, v)
        for f, v in self.clinvar_fields.items():
            self._make_metadata(f, v)
        self._make_metadata('RSID', {'type': 'String',
                                     'description': 'dbSNP ID'})
