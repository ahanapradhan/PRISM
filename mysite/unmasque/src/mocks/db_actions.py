import re


class DbBase:
    def nullify_except(self, D, s_set):
        raise NotImplementedError("method not implemented")

    def run_query(self, Ddot, QH):
        raise NotImplementedError("method not implemented")


class DbMock(DbBase):
    mock = "mock"

    def nullify_except(self, D, s_set):
        print("DbMock...get_Ddot")
        print(D)
        print(s_set)
        diff = D.difference(s_set)
        print(diff)
        return diff

    def run_query(self, Ddot, QH):
        print("DbMock...run_query")
        print(QH)
        print(Ddot)
        return self.mock


class DbParser:

    def __init__(self):
        self.parttabs_qi = None
        self.fromtabs_qi = None
        self.parttab_QH = None
        self.comtab_QH = None
        self.fromtab_QH = None

    FROM_BOUNDARY = r'(?:\bWHERE\b|\bGROUP\s+BY\b|\bORDER\s+BY\b|\bHAVING\b|\bLIMIT\b|$)'

    def reset(self):
        self.fromtab_QH = set()
        self.comtab_QH = set()
        self.parttab_QH = set()
        self.fromtabs_qi = []
        self.parttabs_qi = []

    def _tables_in_from(self, sql):
        """Extract base table names from the FROM clause of a (sub)query."""
        match = re.search(r'\bFROM\b(.*?)' + self.FROM_BOUNDARY, sql, re.IGNORECASE | re.DOTALL)
        if match is None:
            return set()
        tables = set()
        for item in match.group(1).split(","):
            token = item.strip()
            if not token:
                continue
            # Drop an optional alias: "partsupp ps" -> "partsupp".
            name = token.split()[0].strip("();").lower()
            if name:
                tables.add(name)
        return tables

    def parse(self, sql):
        self.reset()
        subqueries = re.findall(r'\((.*?)\)', sql)
        print(len(subqueries))

        if not len(subqueries):  # no union case
            self.fromtab_QH = self._tables_in_from(sql)
            return

        for subquery in subqueries:
            tables = self._tables_in_from(subquery)
            self.fromtabs_qi.append(tables)
            print(sorted(tables))

        # Find tables present in all subqueries
        self.comtab_QH = set.intersection(*self.fromtabs_qi)
        print(self.comtab_QH)

        for ft in self.fromtabs_qi:
            self.parttabs_qi.append(ft - self.comtab_QH)
            print(self.parttabs_qi)

        self.fromtab_QH = set().union(*self.fromtabs_qi)
        self.parttab_QH = set().union(*self.parttabs_qi)

    def print(self):
        print("fromtab_QH")
        print(self.fromtab_QH)
        print("comtab_QH")
        print(self.comtab_QH)
        print("parttab_QH")
        print(self.parttab_QH)
        print("fromtabs_qi")
        print(self.fromtabs_qi)
        print("parttabs_qi")
        print(self.parttabs_qi)
