# @File: annual_report_extractor.py
# @Author: haodingkui
# @Date: 2019-07-09

import re
import pdfplumber

class AnnualReportExtractor(object):
    """上市公司年报信息抽取工具"""

    def __init__(self, report_path):
        self.pdf = pdfplumber.open(report_path)
        self.table_of_contents = self._get_table_of_contents()

    def _get_table_of_contents(self):
        """获取年报的目录"""
        for page_number in range(0, 20):
            raw_text = self.pdf.pages[page_number].extract_text()
            if raw_text is None:
                text = ""
            else:
                text = raw_text.replace(" ", "").replace("  ", "")
            if "目录" in text:
                return text

    def _get_chapter_begin_page_number(self, chapter_name):
        """从目录中获取指定章节开始的页码"""
        begin_page_number = -1
        # 从目录中匹配章节的页码
        match_result = re.findall(chapter_name + r".*[0-9]+", self.table_of_contents)
        if len(match_result) > 0:
            begin_page_number = int(re.findall("[0-9]+", match_result[0])[0])
        return begin_page_number

    def _get_financial_table(self, page_text, page_tables, page_number, fp_keyword, ep_keyword):
        """利用表格第一页和最后一页的关键词抽取财务报表"""
        financial_table = []
        if "项目 " not in page_text:
            page_number = page_number + 1
            page_tables = self.pdf.pages[page_number].extract_tables()
        for table in page_tables:
            if "项目" in table[0]:
                financial_table = table
                break
        # 如果表不止有1页
        page_2 = self.pdf.pages[page_number+1]
        page_2_text = page_2.extract_text()
        page_2_tables = page_2.extract_tables()
        if page_2_tables:
            financial_table += page_2_tables[0]
        # 如果表不止有2页
        if ep_keyword not in page_2_text:
            page_3 = self.pdf.pages[page_number + 2]
            page_3_tables = page_3.extract_tables()
            if page_3_tables:
                if len(page_3_tables) == 1:
                    financial_table += page_3_tables[0]
                if len(page_3_tables) == 2:
                    for table in page_3_tables:
                        if "项目" not in table[0]:
                            financial_table += table
            
        return financial_table

    def get_financial_tables(self):
        """抽取财务报告中的财务报表"""
        financial_tables = {}
        financial_tables["合并资产负债表"] = []
        financial_tables["母公司资产负债表"] = []
        financial_tables["合并利润表"] = []
        financial_tables["母公司利润表"] = []
        financial_tables["合并现金流量表"] = []
        financial_tables["母公司现金流量表"] = []

        financial_report_begin_page_number = self._get_chapter_begin_page_number("财务报告")
        reference_documents_begin_page_number = self._get_chapter_begin_page_number("备查文件目录")

        # 遍历指定页码范围的页面
        for page_number in range(financial_report_begin_page_number, reference_documents_begin_page_number):
            page = self.pdf.pages[page_number]
            page_text = page.extract_text()
            page_tables = page.extract_tables()
            # 如果本页有合并资产负债表的第一页
            if "合并资产负债表" in page_text and "编制单位" in page_text:
                financial_tables["合并资产负债表"] = self._get_financial_table(page_text, page_tables, page_number, 
                                                    "合并资产负债表", "负债和所有者权益")
            if "母公司资产负债表" in page_text and "编制单位" in page_text:                                     
                financial_tables["母公司资产负债表"] = self._get_financial_table(page_text, page_tables, page_number, 
                                                    "母公司资产负债表", "负债和所有者权益")
            if "合并利润表" in page_text and "单位" in page_text:
                financial_tables["合并利润表"] = self._get_financial_table(page_text, page_tables, page_number,
                                                    "合并利润表", "稀释每股收益")
            if "母公司利润表" in page_text and "单位" in page_text:
                financial_tables["母公司利润表"] = self._get_financial_table(page_text, page_tables, page_number,
                                                    "母公司利润表", "稀释每股收益")                                    
            if "合并现金流量表" in page_text and "单位" in page_text:
                financial_tables["合并现金流量表"] = self._get_financial_table(page_text, page_tables, page_number,
                                                    "合并现金流量表", "期末现金及现金等价物余额")
            if "母公司现金流量表" in page_text and "单位" in page_text:
                financial_tables["母公司现金流量表"] = self._get_financial_table(page_text, page_tables, page_number,
                                                    "母公司现金流量表", "期末现金及现金等价物余额")                                      

        return financial_tables


if __name__=="__main__":
    report_path = "data/2018晨光文具年度报告.pdf"
    extractor = AnnualReportExtractor(report_path)
    financial_tables = extractor.get_financial_tables()
    print(financial_tables)
