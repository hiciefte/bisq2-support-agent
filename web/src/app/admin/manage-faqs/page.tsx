"use client"

import { useState, useEffect, FormEvent } from 'react';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardFooter, CardDescription } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog";
import { Pencil, Trash2, Loader2, PlusCircle } from 'lucide-react';
import { useRouter } from 'next/navigation';

interface FAQ {
  id: string;
  question: string;
  answer: string;
  category: string;
  source: string;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function ManageFaqsPage() {
  const [faqs, setFaqs] = useState<FAQ[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingFaq, setEditingFaq] = useState<FAQ | null>(null);
  const [formData, setFormData] = useState({ question: '', answer: '', category: '', source: 'Manual' });
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [loginError, setLoginError] = useState('');
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    const storedApiKey = localStorage.getItem('admin_api_key');
    if (storedApiKey) {
      setApiKey(storedApiKey);
      fetchFaqs(storedApiKey);
    } else {
      setIsLoading(false);
    }
  }, []);

  const fetchFaqs = async (key: string) => {
    setIsLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/admin/faqs`, {
        headers: { 'X-API-KEY': key },
      });
      if (response.ok) {
        const data = await response.json();
        setFaqs(data.faqs);
        setError(null);
      } else {
        const errorText = `Failed to fetch FAQs. Status: ${response.status}`;
        console.error(errorText);
        setError(errorText);
        if (response.status === 401) {
          setLoginError('Invalid API Key.');
          setApiKey(null);
          localStorage.removeItem('admin_api_key');
        }
      }
    } catch (error) {
      const errorText = 'An unexpected error occurred while fetching FAQs.';
      console.error(errorText, error);
      setError(errorText);
    } finally {
      setIsLoading(false);
    }
  };

  const handleLogin = (e: FormEvent) => {
    e.preventDefault();
    const key = (e.target as HTMLFormElement).apiKey.value;
    if (key) {
      localStorage.setItem('admin_api_key', key);
      setApiKey(key);
      setLoginError('');
      fetchFaqs(key);
    }
  };
  
  const handleLogout = () => {
    localStorage.removeItem('admin_api_key');
    setApiKey(null);
    setFaqs([]);
    router.push('/admin/manage-faqs');
  };

  const handleFormSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!apiKey) return;
    setIsSubmitting(true);
    const url = editingFaq ? `${API_BASE_URL}/admin/faqs/${editingFaq.id}` : `${API_BASE_URL}/admin/faqs`;
    const method = editingFaq ? 'PUT' : 'POST';

    try {
      const response = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          'X-API-KEY': apiKey,
        },
        body: JSON.stringify(formData),
      });

      if (response.ok) {
        fetchFaqs(apiKey);
        setIsFormOpen(false);
        setEditingFaq(null);
        setFormData({ question: '', answer: '', category: '', source: 'Manual' });
        setError(null);
      } else {
        const errorText = `Failed to save FAQ. Status: ${response.status}`;
        console.error(errorText);
        setError(errorText);
      }
    } catch (error) {
      const errorText = 'An unexpected error occurred while saving the FAQ.';
      console.error(errorText, error);
      setError(errorText);
    } finally {
      setIsSubmitting(false);
    }
  };
  
  const handleEdit = (faq: FAQ) => {
    setEditingFaq(faq);
    setFormData({ question: faq.question, answer: faq.answer, category: faq.category, source: faq.source });
    setIsFormOpen(true);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };
  
  const handleDelete = async (id: string) => {
    if (!apiKey) return;
    setIsSubmitting(true);
    try {
      const response = await fetch(`${API_BASE_URL}/admin/faqs/${id}`, {
        method: 'DELETE',
        headers: { 'X-API-KEY': apiKey },
      });

      if (response.ok) {
        fetchFaqs(apiKey);
        setError(null);
      } else {
        const errorText = `Failed to delete FAQ. Status: ${response.status}`;
        console.error(errorText);
        setError(errorText);
      }
    } catch (error) {
      const errorText = 'An unexpected error occurred while deleting the FAQ.';
      console.error(errorText, error);
      setError(errorText);
    } finally {
      setIsSubmitting(false);
    }
  };
  
  const openNewFaqForm = () => {
    setEditingFaq(null);
    setFormData({ question: '', answer: '', category: '', source: 'Manual' });
    setIsFormOpen(true);
    setError(null);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  if (!apiKey) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle className="text-2xl font-bold text-center">Admin Login</CardTitle>
            <CardDescription>Enter your API key to manage FAQs.</CardDescription>
          </CardHeader>
          <form onSubmit={handleLogin}>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="apiKey">API Key</Label>
                <Input id="apiKey" name="apiKey" type="password" required />
              </div>
              {loginError && <p className="text-sm text-red-500">{loginError}</p>}
            </CardContent>
            <CardFooter>
              <Button type="submit" className="w-full">Login</Button>
            </CardFooter>
          </form>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto p-4 md:p-8 space-y-8">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold">FAQ Management</h1>
        <Button onClick={handleLogout} variant="outline">Logout</Button>
      </div>

      {error && (
        <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative" role="alert">
            <strong className="font-bold">Error: </strong>
            <span className="block sm:inline">{error}</span>
        </div>
      )}

      {isFormOpen && (
        <Card>
          <CardHeader>
            <CardTitle>{editingFaq ? 'Edit FAQ' : 'Add New FAQ'}</CardTitle>
            <CardDescription>
              {editingFaq ? 'Update the details for this FAQ.' : 'Fill out the form to add a new FAQ to the knowledge base.'}
            </CardDescription>
          </CardHeader>
          <form onSubmit={handleFormSubmit}>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="question">Question</Label>
                <Input id="question" value={formData.question} onChange={(e) => setFormData({ ...formData, question: e.target.value })} required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="answer">Answer</Label>
                <Textarea id="answer" value={formData.answer} onChange={(e) => setFormData({ ...formData, answer: e.target.value })} required />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="category">Category</Label>
                  <Input id="category" value={formData.category} onChange={(e) => setFormData({ ...formData, category: e.target.value })} required />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="source">Source</Label>
                  <Input id="source" value={formData.source} onChange={(e) => setFormData({ ...formData, source: e.target.value })} disabled />
                </div>
              </div>
            </CardContent>
            <CardFooter className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setIsFormOpen(false)}>Cancel</Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                {editingFaq ? 'Save Changes' : 'Add FAQ'}
              </Button>
            </CardFooter>
          </form>
        </Card>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>FAQ List</CardTitle>
              <CardDescription>View, edit, or delete existing FAQs.</CardDescription>
            </div>
            {!isFormOpen && (
              <Button onClick={openNewFaqForm}>
                <PlusCircle className="mr-2 h-4 w-4" /> Add New FAQ
              </Button>
            )}
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : faqs.length === 0 ? (
            <div className="text-center py-12">
              <h3 className="text-lg font-semibold">No FAQs Found</h3>
              <p className="text-muted-foreground mt-1">Get started by adding a new FAQ.</p>
              {!isFormOpen && (
                  <Button onClick={openNewFaqForm} className="mt-4">
                    <PlusCircle className="mr-2 h-4 w-4" /> Add New FAQ
                  </Button>
              )}
            </div>
          ) : (
            <div className="border rounded-md">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Question</TableHead>
                    <TableHead>Answer</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {faqs.map((faq) => (
                    <TableRow key={faq.id}>
                      <TableCell className="font-medium max-w-xs truncate">{faq.question}</TableCell>
                      <TableCell className="max-w-xs truncate">{faq.answer}</TableCell>
                      <TableCell>{faq.category}</TableCell>
                      <TableCell>{faq.source}</TableCell>
                      <TableCell className="text-right space-x-1">
                        <Button variant="ghost" size="icon" onClick={() => handleEdit(faq)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                         <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button variant="ghost" size="icon" disabled={isSubmitting}>
                              <Trash2 className="h-4 w-4 text-red-500" />
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>Are you absolutely sure?</AlertDialogTitle>
                              <AlertDialogDescription>
                                This action cannot be undone. This will permanently delete this FAQ.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Cancel</AlertDialogCancel>
                              <AlertDialogAction onClick={() => handleDelete(faq.id)}>Continue</AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
} 