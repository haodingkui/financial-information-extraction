# @File: annual_report_extractor.py
# @Author: haodingkui
# @Date: 2019-07-09

import os
import re
import json
import yaml
import csv
import pdfplumber
import requests
from pyltp import SentenceSplitter

from PHBS.utils import logger
from PHBS.extract import get_event
from PHBS.new_data_import_format import get_keywords, get_company
from PHBS.handlers.ltp_handler import NlpHandler
from PHBS.handlers.text_handler import TextHandler


class AnnualReportExtractor(object):
    """上市公司年报信息抽取工具"""

    def __init__(self, report_path, result_path):
        self.config = self.load_config_file('../PHBS/configs/config.yaml')
        self.nlp_handler = NlpHandler(self.config)
        self.text_handler = TextHandler('../PHBS/configs/config.yaml')
        self.report_path = report_path
        self.result_path = result_path
        self.pdf = pdfplumber.open(report_path)
        self.table_of_contents = self.get_table_of_contents()
        self.report_file_name = re.findall(r"\d+.*\.pdf", report_path)[0]

        self.financial_table_page_begin_number = 0
        self.financial_table_page_end_number = 0
        self.get_financial_table_page_range()
        # 初始化各表格待插入位置
        self.consolidated_balance_sheet_block_index = 0
        self.parent_company_balance_sheet_block_index = 0
        self.consolidated_income_statement_block_index = 0
        self.parent_income_statement_block_index = 0
        self.consolidated_cash_flow_statement_block_index = 0
        self.parent_cash_flow_statement_block_index = 0
        # 初始化各表格
        self.consolidated_balance_sheet = []
        self.parent_company_balance_sheet = []
        self.consolidated_income_statement = []
        self.parent_income_statement = []
        self.consolidated_cash_flow_statement = []
        self.parent_cash_flow_statement = []

    def load_config_file(self, config_path):
        """加载配置文件"""
        config = yaml.load(open(config_path, 'r'), Loader=yaml.FullLoader)
        return config

    def get_table_of_contents(self):
        """获取年报的目录内容"""
        for page_number in range(0, 20):
            raw_text = self.pdf.pages[page_number].extract_text()
            if raw_text is None:
                text = ""
            else:
                text = raw_text.replace(" ", "").replace("  ", "")
            if "目录" in text:
                return text

    def get_chapter_begin_page_number(self, chapter_name):
        """获取章节开始的页码"""
        begin_page_number = -1
        # 从目录中匹配章节的页码
        match_result = re.findall(chapter_name + r".*[0-9]+", self.table_of_contents)
        if len(match_result) > 0:
            begin_page_number = int(re.findall("[0-9]+", match_result[0])[0])
        return begin_page_number

    @staticmethod
    def get_begin_word_of_table(table: list):
        """获取表格的起始词"""
        begin_word_of_table = ''
        # 获取表格的左上角第一个词
        for row in table[0:len(table)]:
            find_flag = False
            for k1 in row:
                if k1 is not None and k1 != "":
                    begin_word_of_table  = k1
                    find_flag = True
                    break
            if find_flag:
                break
        # 如果单元格内容过长，则截取其最后10个字符作为关键词
        if len(begin_word_of_table) > 50:
            begin_word_of_table = begin_word_of_table[-10:]
        return begin_word_of_table

    @staticmethod
    def get_end_word_of_table(table):
        """获取表格的结束词"""
        end_word_of_table = ''
        # 获取表格的右下角最后一个词
        for row in reversed(table[0:len(table)]):
            find_flag = False
            for k2 in reversed(row):
                if k2 is not None and k2 != "":
                    end_word_of_table = k2
                    find_flag = True
                    break
            if find_flag:
                break
        # 如果单元格内容过长，则截取其最后10个字符作为关键词
        if len(end_word_of_table) > 50:
            end_word_of_table = end_word_of_table[-10:]
        # 如果单元格内容包含换行符，截取前半段
        if "\n" in end_word_of_table:
            end_word_of_table = end_word_of_table[0:end_word_of_table.index("\n")]
        return end_word_of_table

    def get_keywords_of_tables(self, page_tables):
        """获取获取页面中所有表格的起始词和结束词"""
        keywords_of_tables = list()
        if page_tables is not None:
            for table in page_tables:
                begin_word_of_table = self.get_begin_word_of_table(table)
                end_word_of_table = self.get_end_word_of_table(table)
                keywords_of_table = [begin_word_of_table, end_word_of_table]
                keywords_of_tables.append(keywords_of_table)
        return keywords_of_tables

    def get_financial_table_page_range(self):
        """获取主要财务报表的页面范围，后续仅抽取这个范围内的表格"""
        financial_report_begin_page_number = self.get_chapter_begin_page_number("财务报告")
        reference_documents_begin_page_number = self.get_chapter_begin_page_number("备查文件目录")
        # 初始化为财务报告的起始和终止页码
        self.financial_table_page_begin_number = financial_report_begin_page_number
        self.financial_table_page_end_number = reference_documents_begin_page_number
        # 页面数组从0开始，实际页码需要减1
        for page_number in range(financial_report_begin_page_number-1, reference_documents_begin_page_number-1):
            page_1 = self.pdf.pages[page_number]
            page_1_text = page_1.extract_text()
            if "合并资产负债表" in page_1_text and "编制单位" in page_1_text:
                self.financial_table_page_begin_number = page_number
            if "母公司现金流量表 " in page_1_text:
                self.financial_table_page_end_number = page_number + 1
                break

    def ner_time_improve(self, nt):
        flag = True
        if '.' in nt:
            flag = False
        if '-' in nt:
            time_pat = r"20[0-9]\d+-\d+-\d+|19[0-9]\d+-\d+-\d+|20[0-9]\d+-\d+|19[0-9]\d+-\d+|20[0-9]\d+/\d+|19[0-9]\d+/\d+"
            if not re.findall(time_pat, nt):
                flag = False
        return flag

    def get_ner(self, sent, max_line=600):
        data = []
        headers = {'content-type': "application/json", "Accept": "application/json"}

        try:
            r = requests.post('http://192.168.2.251:30000/api/v1/nlp/ner',
                              data=json.dumps({'text': sent}), headers=headers)
            r_text = json.loads(r.text)
            tmp = {}
            tmp["entities"] = r_text["nes"]
            tmp["text"] = r_text["text"]
            if tmp["entities"]:
                tmp.pop('text')
                for element in tmp["entities"]:
                    element["word"] = element.pop("text")
                    if element['ne'] == 'nt' and not self.ner_time_improve(element['word']):
                        del tmp[element]
                        continue
                    element["type"] = element.pop("ne")
            data.append(tmp)
        except:
            pass
        if data:
            return data[0]['entities']
        else:
            return []

    def get_event_idx(self, origin_element, sentence, normalized_element=None, coordinate=None):
        if sentence == "table":
            event_element_message = {
                # 'normalized_element': origin_element,
                'word': origin_element,
                # 'length': len(origin_element),
                'coordinate': coordinate
            }
            return event_element_message
        if sentence != "":
            if not normalized_element:
                normalized_element = origin_element
            event_element_message = {
                # 'normalized_element': normalized_element,
                'word': origin_element,
                # 'length': len(origin_element),
                'offset': sentence.find(origin_element) if sentence.find(origin_element) + 1 else ''
            }
            return event_element_message

    @staticmethod
    def get_cell_position_info(self, origin_element, coordinate=None):
        """组合主体所在单元格的位置信息字典"""
        cell_position_info = {
            'word': origin_element,
            'length': len(origin_element),
            'coordinate': coordinate
        }
        return cell_position_info

    def get_table_events(self, table, table_name):
        """抽取表格中的事件信息"""
        time = int(re.findall(r"\d+年", self.report_file_name)[0].replace("年", ""))
        table_events = []
        action_1 = ""
        action_2 = ""
        if len(table[0]) == 3:
            action_1 = table[0][1]
            action_2 = table[0][2]
        if len(table[0]) == 4:
            action_1 = table[0][2]
            action_2 = table[0][3]
        if action_1 is None or action_1 == "" or "," in action_1:
            action_1 = "为"
        if action_2 is None or action_2 == "" or "," in action_2:
            action_2 = "为"
        for row_number, row in enumerate(table[1:]):
            if len(row) == 3:
                for index, element in enumerate(row):
                    if element is None:
                        row[index] = ""
                if row[1].replace(" ", "") != "":
                    # 主体词在表格中的坐标
                    mainbody_coordinate = {
                        "row": row_number + 1,
                        "column": 1
                    }
                    # row_1_event = {
                    #     'mainbody': self.get_event_idx(row[0], "table", coordinate=mainbody_coordinate),
                    #     'action': self.get_event_idx(action_1, "table"),
                    #     'param': self.get_event_idx(row[1], "table"),
                    #     'time': self.get_event_idx(str(time), "table"),
                    # }
                    row_1_event = {
                        'param' : [self.get_event_idx(row[1], "table")],
                        'time' : [self.get_event_idx(str(time), "table")],
                        'action' : [self.get_event_idx(action_1, "table")],
                        'condition' : [],
                        'program' : [],
                        'subjf' : [self.get_event_idx(table_name, "table")],
                        'objf' : [],
                        'subjs' : [self.get_event_idx(row[0], "table", coordinate=mainbody_coordinate)]
                    }
                    table_events.append(row_1_event)
                if row[2].replace(" ", "") != "":
                    mainbody_coordinate = {
                        "row": row_number + 1,
                        "column": 2
                    }
                    # row_2_event = {
                    #     'mainbody': self.get_event_idx(row[0], "table", coordinate=mainbody_coordinate),
                    #     'action': self.get_event_idx(action_2, "table"),
                    #     'param': self.get_event_idx(row[2], "table"),
                    #     'time': self.get_event_idx(str(time - 1), "table")
                    # }
                    row_2_event = {
                        'param': [self.get_event_idx(row[2], "table")],
                        'time': [self.get_event_idx(str(time - 1), "table")],
                        'action': [self.get_event_idx(action_2, "table")],
                        'condition': [],
                        'program': [],
                        'subjf': [self.get_event_idx(table_name, "table")],
                        'objf': [],
                        'subjs': [self.get_event_idx(row[0], "table", coordinate=mainbody_coordinate)]
                    }
                    table_events.append(row_2_event)

            if len(row) == 4:
                for index, element in enumerate(row):
                    if element is None:
                        row[index] = ""
                if row[2].replace(" ", "") != "":
                    mainbody_coordinate = {
                        "row": row_number + 1,
                        "column": 2
                    }
                    # row_1_event = {
                    #     'mainbody': self.get_event_idx(row[0], "table", coordinate=mainbody_coordinate),
                    #     'action': self.get_event_idx(action_1, "table"),
                    #     'param': self.get_event_idx(row[2], "table"),
                    #     'time': self.get_event_idx(str(time), "table")
                    # }
                    row_1_event = {
                        'param': [self.get_event_idx(row[2], "table")],
                        'time': [self.get_event_idx(str(time), "table")],
                        'action': [self.get_event_idx(action_1, "table")],
                        'condition': [],
                        'program': [],
                        'subjf': [self.get_event_idx(table_name, "table")],
                        'objf': [],
                        'subjs': [self.get_event_idx(row[0], "table", coordinate=mainbody_coordinate)]
                    }
                    table_events.append(row_1_event)
                if row[3].replace(" ", "") != "":
                    mainbody_coordinate = {
                        "row": row_number + 1,
                        "column": 3
                    }
                    # row_2_event = {
                    #     'mainbody': self.get_event_idx(row[0], "table",coordinate=mainbody_coordinate),
                    #     'action': self.get_event_idx(action_2, "table"),
                    #     'param': self.get_event_idx(row[3], "table"),
                    #     'time': self.get_event_idx(str(time - 1), "table")
                    # }
                    row_2_event = {
                        'param': [self.get_event_idx(row[3], "table")],
                        'time': [self.get_event_idx(str(time - 1), "table")],
                        'action': [self.get_event_idx(action_2, "table")],
                        'condition': [],
                        'program': [],
                        'subjf': [self.get_event_idx(table_name, "table")],
                        'objf': [],
                        'subjs': [self.get_event_idx(row[0], "table", coordinate=mainbody_coordinate)]
                    }
                    table_events.append(row_2_event)

        return table_events

    def get_table_info(self, table, table_name):
        """获取表格中的事件信息"""
        if not table:
            return []
        table_events = self.get_table_events(table, table_name)
        table_info = {
            'events': table_events,
            'text': "table",
            'table': table
        }
        return table_info

    def get_text_info(self, text):
        """获取文本中的实体、事件信息"""
        if text == "":
            return {
                'entities': [],
                'events': [],
                'text': ""
            }
        # text_entities = self.get_ner(text)
        text_entities = []
        # text_events = get_event(text)
        text_events = self.text_handler.get_sentence_events(text)
        # text_events = []
        text_info = {
            'entities': text_entities,
            'events': text_events,
            'text': text
        }
        return text_info

    def get_block_info_list(self, block_list):
        """获取文本块中的句子列表"""
        block_info_list = []
        for block in block_list:
            sents = []
            sents.extend(SentenceSplitter.split(block))
            sent_info_list = []
            for sent in sents:
                # 删除句子中的空格、制表符、换行符
                sent = sent.replace(" ", "").replace(" ", "").replace("\n", "")
                sent_info  = self.get_text_info(sent)
                sent_info_list.append(sent_info)
            block_info_list.append(sent_info_list)
        return block_info_list

    def split_page(self, page_text, page_tables, page_number, report_info_list):
        """将普通页面分割为文本块"""
        block_list = []
        keywords_of_tables = []
        if page_tables != [] and page_number in range(self.financial_table_page_begin_number,self.financial_table_page_end_number):
            keywords_of_tables = self.get_keywords_of_tables(page_tables)
            for keywords_of_table in keywords_of_tables:
                if keywords_of_table[0] + " " in page_text and keywords_of_table[1] in page_text :
                    begin_index = page_text.index(keywords_of_table[0] + " ")
                    end_index = page_text.index(keywords_of_table[1]) + len(keywords_of_table[1])
                    block_1 = page_text[0:begin_index]
                    block_list.append(block_1)

                    if "合并资产负债表" in block_1 and "编制单位" in block_1:
                        self.consolidated_balance_sheet_block_index = len(report_info_list) + len(block_list)
                        page_text = block_1 + page_text[end_index:]
                        continue

                    if "母公司资产负债表" in page_text:
                        if "项目" in page_text:
                            self.parent_company_balance_sheet_block_index = len(report_info_list) + len(block_list) + 1
                        else:
                            self.parent_company_balance_sheet_block_index = len(report_info_list) + len(block_list) + 3
                            block_list.append(page_text[end_index:])
                        page_text = block_1 + page_text[end_index:]
                        continue

                    if "合并利润表" in page_text:
                        if "项目" in page_text:
                            self.consolidated_income_statement_block_index = len(report_info_list) + len(block_list) + 2
                        else:
                            self.consolidated_income_statement_block_index = len(report_info_list) + len(block_list) + 4
                            block_list.append(page_text[end_index:])
                        page_text = block_1 + page_text[end_index:]
                        continue

                    if "母公司利润表" in page_text:
                        if "项目" in page_text:
                            self.parent_income_statement_block_index = len(report_info_list) + len(block_list) + 3
                        else:
                            self.parent_income_statement_block_index = len(report_info_list) + len(block_list) + 5
                            block_list.append(page_text[end_index:])
                        page_text = block_1 + page_text[end_index:]
                        continue

                    if "合并现金流量表" in page_text:
                        if "项目" in page_text:
                            self.consolidated_cash_flow_statement_block_index = \
                                len(report_info_list) + len(block_list) + 4
                        else:
                            self.consolidated_cash_flow_statement_block_index = \
                                len(report_info_list) + len(block_list) + 6
                            block_list.append(page_text[end_index:])
                        page_text = block_1 + page_text[end_index:]
                        continue

                    if "母公司现金流量表" in page_text:
                        if "项目" in page_text:
                            self.parent_cash_flow_statement_block_index = len(report_info_list) + len(block_list) + 5
                        else:
                            self.parent_cash_flow_statement_block_index = len(report_info_list) + len(block_list) + 7
                            block_list.append(page_text[end_index:])
                        page_text = block_1 + page_text[end_index:]
                        continue
                    # table_text = page_text[begin_index:end_index]
                    # block_list.append(table_text)
                    page_text = block_1 + page_text[end_index:]
        else:
            block_list = page_text.split("\n \n")
        return block_list

    def get_report_info_list(self, begin_page_number, end_page_number):
        """获取年报信息列表，每个元素包含年报一块（block）内容的知识点信息"""
        report_text = ""
        report_info_list = []
        # 遍历指定页码范围的页面
        for page_number in range(begin_page_number, end_page_number):
            page = self.pdf.pages[page_number]
            page_text = page.extract_text()
            page_tables = page.extract_tables()
            # 如果本页有合并资产负债表的第一页
            if "合并资产负债表" in page_text and "编制单位" in page_text:
                # self.consolidated_balance_sheet_block_index = len(report_info_list)
                if "项目 " not in page_text:
                    page_number = page_number + 1
                    page_tables = self.pdf.pages[page_number].extract_tables()
                self.consolidated_balance_sheet = page_tables[0]
                # 如果合并资产负债表不止有1页
                if "负债和所有者权益" not in page_text:
                    page_2 = self.pdf.pages[page_number+1]
                    page_2_text = page_2.extract_text()
                    page_2_tables = page_2.extract_tables()
                    if page_2_tables:
                        self.consolidated_balance_sheet += page_2_tables[0]
                    # 如果合并资产负债表不止有2页
                    if "负债和所有者权益" not in page_2_text:
                        page_3 = self.pdf.pages[page_number + 2]
                        page_3_tables = page_3.extract_tables()
                        if page_3_tables:
                            if len(page_3_tables) == 1:
                                self.consolidated_balance_sheet += page_3_tables[0]
                            if len(page_3_tables) == 2:
                                for table in page_3_tables:
                                    if "项目" not in table[0]:
                                        self.consolidated_balance_sheet += table

            if "母公司资产负债表" in page_text:
                if "项目" not in page_text :
                    page_number = page_number + 1
                    page_tables = self.pdf.pages[page_number].extract_tables()
                if len(page_tables) == 1:
                    self.parent_company_balance_sheet = page_tables[0]
                if len(page_tables) == 2:
                    self.parent_company_balance_sheet = page_tables[1]
                # 如果合并资产负债表不止有1页
                page_2 = self.pdf.pages[page_number+1]
                page_2_text = page_2.extract_text()
                page_2_tables = page_2.extract_tables()
                if page_2_tables:
                    self.parent_company_balance_sheet += page_2_tables[0]
                if "负债和所有者权益" not in page_2_text:
                    page_3 = self.pdf.pages[page_number+2]
                    page_3_tables = page_3.extract_tables()
                    if page_3_tables:
                        if len(page_3_tables) == 1:
                            self.parent_company_balance_sheet += page_3_tables[0]
                        if len(page_3_tables) == 2:
                            for table in page_3_tables:
                                if "项目" not in table[0]:
                                    self.parent_company_balance_sheet += table

            if "合并利润表" in page_text:
                if "项目" not in page_text and "会计机构负责人" in page_text:
                    page_number = page_number + 1
                    page_tables = self.pdf.pages[page_number].extract_tables()
                for table in page_tables:
                    if "项目" in table[0]:
                        self.consolidated_income_statement = table
                        break
                # 如果合并利润表不止有1页
                page_2 = self.pdf.pages[page_number+1]
                page_2_text = page_2.extract_text()
                page_2_tables = page_2.extract_tables()
                if page_2_tables:
                    self.consolidated_income_statement += page_2_tables[0]
                if "稀释每股收益" not in page_2_text:
                    page_3 = self.pdf.pages[page_number+2]
                    page_3_tables = page_3.extract_tables()
                    if page_3_tables:
                        if len(page_3_tables) == 1:
                            self.consolidated_income_statement += page_3_tables[0]
                        if len(page_3_tables) == 2:
                            for table in page_3_tables:
                                if "项目" not in table[0]:
                                    self.consolidated_income_statement += table

            if "母公司利润表" in page_text :
                if "项目" not in page_text and "会计机构负责人" in page_text:
                    page_number = page_number + 1
                    page_tables = self.pdf.pages[page_number].extract_tables()
                if len(page_tables) == 1:
                    self.parent_income_statement = page_tables[0]
                if len(page_tables) == 2:
                    self.parent_income_statement = page_tables[1]
                # 如果母公司利润表不止有1页
                page_2 = self.pdf.pages[page_number+1]
                page_2_text = page_2.extract_text()
                page_2_tables = page_2.extract_tables()
                if page_2_tables:
                    self.parent_income_statement += page_2_tables[0]
                if "稀释每股收益" not in page_2_text:
                    page_3 = self.pdf.pages[page_number+2]
                    page_3_tables = page_3.extract_tables()
                    if page_3_tables:
                        if len(page_3_tables) == 1:
                            self.parent_income_statement += page_3_tables[0]
                        if len(page_3_tables) == 2:
                            for table in page_3_tables:
                                if "项目" not in table[0]:
                                    self.parent_income_statement += table

            if "合并现金流量表" in page_text:
                if "项目" not in page_text and "会计机构负责人" in page_text:
                    page_number = page_number + 1
                    page_tables = self.pdf.pages[page_number].extract_tables()
                if len(page_tables) == 1:
                    self.consolidated_cash_flow_statement = page_tables[0]
                if len(page_tables) == 2:
                    self.consolidated_cash_flow_statement = page_tables[1]
                # 如果合并现金流量表不止有1页
                page_2 = self.pdf.pages[page_number+1]
                page_2_text = page_2.extract_text()
                page_2_tables = page_2.extract_tables()
                if page_2_tables:
                    self.consolidated_cash_flow_statement += page_2_tables[0]
                if "期末现金及现金等价物余额" not in page_2_text:
                    page_3 = self.pdf.pages[page_number+2]
                    page_3_tables = page_3.extract_tables()
                    if page_3_tables:
                        if len(page_3_tables) == 1:
                            self.consolidated_cash_flow_statement += page_3_tables[0]
                        if len(page_3_tables) == 2:
                            for table in page_3_tables:
                                if "项目" not in table[0]:
                                    self.consolidated_cash_flow_statement += table

            if "母公司现金流量表" in page_text:
                if "项目" not in page_text and "会计机构负责人" in page_text:
                    page_number = page_number + 1
                    page_tables = self.pdf.pages[page_number].extract_tables()
                if len(page_tables) == 1:
                    self.parent_cash_flow_statement = page_tables[0]
                if len(page_tables) == 2:
                    self.parent_cash_flow_statement = page_tables[1]
                # 如果母公司现金流量表不止有1页
                page_2 = self.pdf.pages[page_number+1]
                page_2_text = page_2.extract_text()
                page_2_tables = page_2.extract_tables()
                if page_2_tables:
                    self.parent_cash_flow_statement += page_2_tables[0]
                if "期末现金及现金等价物余额" not in page_2_text:
                    page_3 = self.pdf.pages[page_number+2]
                    page_3_tables = page_3.extract_tables()
                    if page_3_tables:
                        if len(page_3_tables) == 1:
                            self.parent_cash_flow_statement += page_3_tables[0]
                        if len(page_3_tables) == 2:
                            for table in page_3_tables:
                                if "项目" not in table[0]:
                                    self.parent_cash_flow_statement += table

            if page_text is not None:
                report_text += page_text
                page_tables = page.extract_tables()
                block_list = self.split_page(page_text, page_tables, page_number, report_info_list)
                block_info_list = self.get_block_info_list(block_list)
                report_info_list += block_info_list
                logger.info(block_info_list)
        
        consolidated_balance_sheet_info = self.get_table_info(self.consolidated_balance_sheet, "合并资产负债表")
        consolidated_balance_sheet = [consolidated_balance_sheet_info]
        parent_company_balance_sheet_info = self.get_table_info(self.parent_company_balance_sheet, "母公司资产负债表")
        parent_company_balance_sheet = [parent_company_balance_sheet_info]
        consolidated_income_statement_info = self.get_table_info(self.consolidated_income_statement, "合并利润表")
        consolidated_income_statement = [consolidated_income_statement_info]
        parent_income_statement_info = self.get_table_info(self.parent_income_statement, "母公司利润表")
        parent_income_statement = [parent_income_statement_info]
        consolidated_cash_flow_statement_info = self.get_table_info(self.consolidated_cash_flow_statement, "合并现金流量表")
        consolidated_cash_flow_statement = [consolidated_cash_flow_statement_info]
        parent_cash_flow_statement_info = self.get_table_info(self.parent_cash_flow_statement, "母公司现金流量表")
        parent_cash_flow_statement = [parent_cash_flow_statement_info]
        # 将相应表格插入原文特定文本块后面
        report_info_list.insert(self.consolidated_balance_sheet_block_index, consolidated_balance_sheet)
        report_info_list.insert(self.parent_company_balance_sheet_block_index, parent_company_balance_sheet)
        report_info_list.insert(self.consolidated_income_statement_block_index, consolidated_income_statement)
        report_info_list.insert(self.parent_income_statement_block_index, parent_income_statement)
        report_info_list.insert(self.consolidated_cash_flow_statement_block_index, consolidated_cash_flow_statement)
        report_info_list.insert(self.parent_cash_flow_statement_block_index, parent_cash_flow_statement)

        return report_info_list, report_text
